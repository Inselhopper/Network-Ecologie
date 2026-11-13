"""Sequential installation prototype; simulated servo is the only actuator."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import queue
import time

import numpy as np

LOG = logging.getLogger("network")
MIN_ANGLE, MAX_ANGLE = 35.0, 95.0


def mouth_angle(ratio):
    return MIN_ANGLE + np.clip(ratio / 0.65, 0, 1) * (MAX_ANGLE - MIN_ANGLE)


def prepare(audio, rate):
    """Duration-preserving quiet echo and a reordered phrase, all in RAM."""
    response = audio.copy()
    delay = int(rate * .09)
    if len(audio) > delay:
        response[delay:] += .22 * audio[:-delay]
    response = np.clip(response * .75, -.9, .9).astype(np.float32)
    edge = min(int(rate * .03), len(response) // 2)
    if edge:
        response[:edge] *= np.linspace(0, 1, edge)
        response[-edge:] *= np.linspace(1, 0, edge)
    pieces = np.array_split(response, 4)
    gap = np.zeros(int(rate * .15), dtype=np.float32)
    phrase_parts = []
    for index in (0, 2, 1, 2, 3):
        piece = pieces[index].copy()
        n = min(int(rate * .015), len(piece) // 2)
        if n:
            piece[:n] *= np.linspace(0, 1, n)
            piece[-n:] *= np.linspace(1, 0, n)
        phrase_parts.extend((piece, gap))
    return response, np.concatenate(phrase_parts)


class Audio:
    """Input callback only queues bounded blocks. Playback has its own clock."""
    def __init__(self, args):
        import sounddevice as sd
        self.sd = sd
        self.rate = args.sample_rate
        self.events = queue.Queue(maxsize=128)
        self.accept = False
        self.output = None
        self.position = 0
        self.played = 0
        self.data = np.zeros(0, dtype=np.float32)
        self.output_start = None
        self.statuses = deque(maxlen=32)
        self.input = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                    device=args.input_device, blocksize=1024,
                                    latency="high", callback=self.capture)
        self.output_device = args.output_device

    def capture(self, data, frames, timing, status):
        if status:
            self.statuses.append(str(status))
        if not self.accept:
            return
        # PortAudio ADC time mapped onto the application's monotonic clock.
        stamp = time.perf_counter() + timing.inputBufferAdcTime - timing.currentTime
        try:
            self.events.put_nowait((stamp, data[:, 0].copy()))
        except queue.Full:
            self.statuses.append("Input queue full: recording aborted")

    def listen(self, enabled):
        self.accept = False
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        self.accept = enabled

    def play(self, data):
        self.stop()
        self.listen(False)
        self.data = data
        self.position = self.played = 0
        self.output_start = None

        def callback(out, frames, timing, status):
            if status:
                self.statuses.append(str(status))
            if self.output_start is None:
                self.output_start = (time.perf_counter() + timing.outputBufferDacTime
                                     - timing.currentTime)
            out.fill(0)
            count = min(frames, len(self.data) - self.position)
            out[:count, 0] = self.data[self.position:self.position + count]
            self.position += count

        self.output = self.sd.OutputStream(samplerate=self.rate, channels=1,
                                          dtype="float32", device=self.output_device,
                                          blocksize=1024, latency="high", callback=callback)
        self.output.start()
        LOG.info("Audio playback: %.2fs", len(data) / self.rate)

    def elapsed(self):
        if self.output_start is None:
            return 0.0
        return max(0.0, time.perf_counter() - self.output_start)

    def finished(self):
        return self.output_start is not None and self.elapsed() >= len(self.data) / self.rate

    def stop(self):
        if self.output is not None:
            self.output.stop()
            self.output.close()
            self.output = None
        self.data = np.zeros(0, dtype=np.float32)

    def close(self):
        self.listen(False)
        self.stop()
        self.input.close()


class Installation:
    def __init__(self, audio, args):
        self.audio, self.args = audio, args
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.angle = MIN_ANGLE
        self.last_update = time.perf_counter()
        self.history = deque(maxlen=30)
        self.reset()

    def transition(self, state):
        LOG.info("State %s -> %s", getattr(self, "state", "START"), state)
        self.state, self.since = state, time.perf_counter()

    def reset(self):
        self.audio.stop()
        self.audio.listen(True)
        self.blocks, self.motion = [], []
        self.response = self.phrase = None
        self.history.clear()
        self.record_start = self.last_voice = None
        self.joined = False
        self.transition("LISTENING")

    def begin_response(self):
        self.audio.play(self.response)
        self.transition("PLAYBACK_RESPONSE")

    def begin_sync(self):
        repeats = math.ceil(self.args.together_seconds * self.audio.rate / len(self.response))
        bed = np.tile(self.response * .55, repeats)[:int(self.args.together_seconds * self.audio.rate)]
        self.audio.play(bed)
        self.transition("SYNCHRONOUS_PLAY")

    def update(self, ratio):
        now = time.perf_counter()
        dt, self.last_update = min(.1, now - self.last_update), now
        live = float(mouth_angle(ratio)) if ratio is not None else MIN_ANGLE
        self.history.append((now, live))
        moving = ratio is not None and ratio > self.args.mouth_threshold
        while self.audio.statuses:
            message = self.audio.statuses.popleft()
            LOG.warning("Audio: %s", message)
            if "queue full" in message:
                raise RuntimeError(message)
        while True:
            try:
                stamp, block = self.audio.events.get_nowait()
            except queue.Empty:
                break
            level = float(np.sqrt(np.mean(block ** 2)))
            voice = level >= self.args.threshold
            if self.state == "LISTENING" and voice:
                self.record_start = self.last_voice = stamp
                self.motion = [(0.0, self.history[0][1] if self.history else live)]
                self.transition("RECORDING_HUMAN")
            if self.state == "RECORDING_HUMAN":
                remaining = max(0, int(self.args.max_record * self.audio.rate)
                                - sum(len(b) for b in self.blocks))
                self.blocks.append(block[:remaining])
                if voice:
                    self.last_voice = stamp + len(block) / self.audio.rate
                duration = sum(len(b) for b in self.blocks) / self.audio.rate
                if duration >= self.args.max_record or stamp - self.last_voice >= self.args.silence:
                    self.audio.listen(False)
                    LOG.info("Recorded %.2fs, %d motion samples", duration, len(self.motion))
                    self.future = self.pool.submit(prepare, np.concatenate(self.blocks), self.audio.rate)
                    self.transition("PROCESSING_RESPONSE")
            elif self.state == "WAITING_FOR_RESPONSE" and voice:
                self.begin_sync()
        target, self.source = MIN_ANGLE, "Ruhe"
        if self.state == "RECORDING_HUMAN":
            self.motion.append((max(0, now - self.record_start), live))
        elif self.state == "PROCESSING_RESPONSE" and self.future.done():
            self.response, self.phrase = self.future.result()
            self.future = None
            self.blocks.clear()
            self.begin_response()
        elif self.state == "PLAYBACK_RESPONSE":
            elapsed = self.audio.elapsed()
            target = float(np.interp(elapsed, [m[0] for m in self.motion], [m[1] for m in self.motion]))
            self.source = "Aufgezeichnetes FaceMesh"
            if self.audio.finished():
                self.audio.stop()
                self.transition("INVITATION_PAUSE")
        elif self.state == "INVITATION_PAUSE" and now - self.since >= 1.5:
            self.audio.listen(True)
            self.transition("WAITING_FOR_RESPONSE")
        elif self.state == "WAITING_FOR_RESPONSE":
            if moving:
                self.begin_sync()
            elif now - self.since > self.args.response_window:
                self.audio.listen(False)
                self.transition("FADE_OUT")
        elif self.state == "SYNCHRONOUS_PLAY":
            target, self.source = live, "FaceMesh live"
            if self.audio.finished():
                self.audio.play(self.phrase)
                self.transition("MACHINE_LEADS")
        elif self.state in ("MACHINE_LEADS", "HUMAN_JOINS"):
            self.source = "Maschinenklang"
            pos = int(self.audio.elapsed() * self.audio.rate)
            chunk = self.audio.data[pos:pos + int(.04 * self.audio.rate)]
            rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0
            target = MIN_ANGLE + min(1, rms * 8) * (MAX_ANGLE - MIN_ANGLE)
            if moving and self.state == "HUMAN_JOINS" and not self.joined:
                self.joined = True
                LOG.info("Participation detected (mouth opening; not a musical match assessment)")
            if self.audio.finished():
                if self.state == "MACHINE_LEADS":
                    self.audio.play(np.tile(self.phrase, 2))
                    self.transition("HUMAN_JOINS")
                else:
                    self.audio.stop()
                    self.transition("FADE_OUT")
        elif self.state == "FADE_OUT" and now - self.since > 2:
            self.reset()
        # One bounded and smoothed actuator output for every state.
        self.angle += (float(np.clip(target, MIN_ANGLE, MAX_ANGLE)) - self.angle) * (1 - math.exp(-dt / .12))

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.blocks.clear()
        self.motion.clear()
        self.history.clear()
        self.response = self.phrase = self.future = None


def parse_args():
    parser = argparse.ArgumentParser(description="Network Ecologie: sequenzieller Dialog mit virtuellem Servo")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--threshold", type=float, default=.025)
    parser.add_argument("--mouth-threshold", type=float, default=.12)
    parser.add_argument("--silence", type=float, default=.7)
    parser.add_argument("--max-record", type=float, default=4)
    parser.add_argument("--response-window", type=float, default=8)
    parser.add_argument("--together-seconds", type=float, default=8)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    for name in ("sample_rate", "threshold", "mouth_threshold", "silence", "max_record", "response_window", "together_seconds", "seconds"):
        value = getattr(args, name)
        if value is not None and (not math.isfinite(value) or value <= 0):
            parser.error(f"--{name.replace('_', '-')} muss positiv und endlich sein")
    return args


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sounddevice as sd
    if args.list_devices:
        print(sd.query_devices())
        return
    import cv2
    from camera import CameraCapture
    from mouth_detector import MouthDetector
    audio = camera = detector = installation = None
    try:
        camera = CameraCapture({"device": args.camera})
        detector = MouthDetector()
        audio = Audio(args)
        installation = Installation(audio, args)
        audio.input.start()
        started = time.perf_counter()
        LOG.info("Servo SIMULATION only. ESC stops. No serial port is opened.")
        while args.seconds is None or time.perf_counter() - started < args.seconds:
            frame = camera.read()
            if frame is None:
                raise RuntimeError("Kamera liefert kein Bild")
            face, ratio = detector.update(frame)
            installation.update(ratio if face else None)
            rows = (installation.state, "SIMULATION | " + installation.source,
                    f"Servo: {installation.angle:.1f} Grad | Face: {face}",
                    "ESC: Ende | Mikrofon nur beim Zuhoeren aktiv")
            for index, text in enumerate(rows):
                cv2.putText(frame, text, (15, 28 + index * 30), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 0), 1)
            opening = int(3 + (installation.angle - MIN_ANGLE) * .7)
            cv2.ellipse(frame, (frame.shape[1] - 100, frame.shape[0] - 90), (65, opening),
                        0, 0, 360, (0, 200, 255), 3)
            cv2.imshow("Network Ecologie - virtueller Mund", frame)
            if cv2.waitKey(1) & 255 == 27:
                break
    except KeyboardInterrupt:
        LOG.info("Stopped by user")
    except Exception:
        LOG.exception("Installation stopped due to an error")
        raise
    finally:
        if audio:
            audio.close()
        if installation:
            installation.close()
        if detector:
            detector.facemesh.close()
        if camera:
            camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
