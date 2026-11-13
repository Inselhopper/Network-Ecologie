# main.py
import argparse
from pathlib import Path
import subprocess
import sys
import time
import cv2
import serial
import serial.tools.list_ports

from camera import CameraCapture
from mouth_detector import MouthDetector
from render_debug import RendererDebug
from servo_controller import ServoController


DEBUG = True

def dbg(*args):
    if DEBUG:
        print(*args)


WINDOW_NAME = "The Power of One"


def map_value(x, in_min, in_max, out_min, out_max):
    if in_max == in_min:
        return out_min

    x = max(in_min, min(in_max, x))
    return out_min + (x - in_min) * (out_max - out_min) / (in_max - in_min)


def connect_servo():
    keywords = ["arduino", "ch340", "usb serial", "ftdi", "usb-sERIAL", "serial"]

    ports = list(serial.tools.list_ports.comports())

    print("Gefundene Ports:")
    for p in ports:
        print(f"  {p.device} - {p.description}")

    for p in ports:
        desc = (p.description or "").lower()

        if any(k.lower() in desc for k in keywords):
            try:
                print(f"Versuche Servo/Arduino auf {p.device} ({p.description})")
                servo = ServoController(p.device)
                print(f"Servo verbunden über {p.device}")
                return servo
            except Exception as e:
                print(f"Port {p.device} ging nicht: {e}")

    for p in ports:
        try:
            print(f"Versuche alternativ {p.device}")
            servo = ServoController(p.device)
            print(f"Servo verbunden über {p.device}")
            return servo
        except Exception as e:
            print(f"Port {p.device} ging nicht: {e}")

    print("Kein Arduino/Servo gefunden - Servo deaktiviert")
    return None


def parse_args():
    parser = argparse.ArgumentParser(description="Kamera, Mund-Erkennung, Servo und Live-Ton")
    parser.add_argument("--audio-mode", choices=("chor", "harmonie", "original", "off"), default="chor")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--seconds", type=float, help="Automatisch nach N Sekunden beenden")
    parser.add_argument("--no-servo", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--host-api", default="auto")
    parser.add_argument("--sample-rate", type=int)
    parser.add_argument("--block-size", type=int)
    parser.add_argument("--latency", choices=("low", "high"), default="low")
    args = parser.parse_args()
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds muss positiv sein")
    return args


def start_audio(args):
    script = Path(__file__).with_name("realtime_3voices.py")
    command = [sys.executable, "-u", str(script), "--mode", args.audio_mode,
               "--parent-control", "--host-api", args.host_api, "--latency", args.latency]
    for name in ("input_device", "output_device", "sample_rate", "block_size"):
        value = getattr(args, name)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), str(value)])
    return subprocess.Popen(command, stdin=subprocess.PIPE, text=True)


def stop_audio(process):
    if process is None:
        return
    try:
        if process.poll() is None:
            try:
                process.stdin.write("stop\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    finally:
        process.stdin.close()


def main():
    args = parse_args()
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    camera = None
    mouth_detector = None
    servo = None
    audio_process = None
    try:
        camera = CameraCapture({"device": args.camera})
        mouth_detector = MouthDetector()
        debug_renderer = RendererDebug()
        dbg("Controls: ESC oder Strg+C beendet Kamera und Ton")
        servo = None if args.no_servo else connect_servo()
        if args.audio_mode != "off":
            audio_process = start_audio(args)
        last_servo_send_t = 0.0
        last_servo_angle = None
        frame_count = 0
        started = time.perf_counter()
        last_print_t = started
        face_ok_false_count = 0
        none_frame_count = 0
        while True:
            now = time.perf_counter()
            if args.seconds is not None and now - started >= args.seconds:
                break
            if audio_process is not None and audio_process.poll() is not None:
                raise RuntimeError(f"Audio-Prozess wurde beendet (Code {audio_process.returncode}). "
                                   "Siehe Audio-Meldung im Terminal.")
            frame_count += 1

            frame = camera.read()

            if frame is None:
                none_frame_count += 1

                if now - last_print_t > 2.0:
                    dbg(f"[WARN] camera.read() returned None (count={none_frame_count})")
                    last_print_t = now

                key = cv2.waitKey(1) & 0xFF

                if key == 27:
                    break

                continue

            face_ok, mouth_open_ratio = mouth_detector.update(frame)

            if face_ok and mouth_open_ratio is not None:
                servo_angle = map_value(mouth_open_ratio, 0.00, 0.65, 35, 95)

                if now - last_servo_send_t > 0.04:
                    print(f"Mund={mouth_open_ratio:.3f}  Servo={servo_angle:.1f}°")

                    if servo is not None:
                        try:
                            servo.set_angle(servo_angle)
                            last_servo_angle = servo_angle
                        except Exception as e:
                            print(f"Servo-Fehler: {e}")
                            servo = None

                    last_servo_send_t = now

            if not face_ok:
                face_ok_false_count += 1


            debug_renderer.render(
                face_ok=face_ok,
                mouth_open_ratio=mouth_open_ratio,
            )

            debug_text_1 = f"Mund: {mouth_open_ratio:.3f}" if mouth_open_ratio is not None else "Mund: None"
            debug_text_2 = f"Servo: {servo_angle:.1f}" if face_ok and mouth_open_ratio is not None else "Servo: --"
            debug_text_3 = f"Face: {face_ok} "

            cv2.putText(frame, debug_text_1, (30, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            cv2.putText(frame, debug_text_2, (30, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            cv2.putText(frame, debug_text_3, (30, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            cv2.imshow(WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                dbg("[KEY] ESC -> exit")
                break


            if now - last_print_t > 2.0:
                dbg(
                    f"face_ok={face_ok} mouth_open_ratio={None if mouth_open_ratio is None else round(mouth_open_ratio, 3)} "
                    f"face_ok_false_total={face_ok_false_count} "
                    f"servo={None if last_servo_angle is None else round(last_servo_angle, 1)}"
                )
                last_print_t = now

    except KeyboardInterrupt:
        print("Kamera und Ton werden beendet.")
    finally:
        stop_audio(audio_process)
        if camera is not None:
            camera.release()
        if mouth_detector is not None:
            mouth_detector.facemesh.close()

        if servo is not None and hasattr(servo, "close"):
            servo.close()

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
