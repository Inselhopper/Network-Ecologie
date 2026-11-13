"""Live voice experiments: speech chorus or fixed three-part harmony."""

import argparse
import sys
import time
import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48000


class ChorusVoice:
    """Short modulated delay, without feedback or external effect plugins."""
    def __init__(self, sample_rate, block_size, delay_ms, depth_ms, rate_hz, phase=0.0):
        self.sample_rate = sample_rate
        self.delay = delay_ms * sample_rate / 1000
        self.depth = depth_ms * sample_rate / 1000
        self.rate_hz = rate_hz
        self.buffer = np.zeros(block_size + int(self.delay + self.depth) + 2,
                               dtype=np.float32)
        self.write_pos = 0
        self.phase = phase
        self.offsets = np.arange(block_size)

    def __call__(self, audio, sample_rate, **kwargs):
        samples = audio.reshape(-1)
        offsets = self.offsets[:len(samples)]
        indices = self.write_pos + offsets
        self.buffer[indices % len(self.buffer)] = samples
        step = 2 * np.pi * self.rate_hz / self.sample_rate
        delay = self.delay + self.depth * np.sin(self.phase + step * offsets)
        positions = indices - delay
        left = np.floor(positions).astype(np.int64)
        fraction = positions - left
        result = (self.buffer[left % len(self.buffer)] * (1 - fraction)
                  + self.buffer[(left + 1) % len(self.buffer)] * fraction)
        self.write_pos = (self.write_pos + len(samples)) % len(self.buffer)
        self.phase = (self.phase + step * len(samples)) % (2 * np.pi)
        return result.astype(np.float32).reshape(1, -1)


class SpectralVoice:
    """Streaming phase vocoder with overlapping FFT windows."""
    def __init__(self, semitones):
        self.ratio = 2 ** (semitones / 12)
        self.size, self.hop = 1024, 256
        self.window = np.hanning(self.size)
        self.input = np.zeros(self.size)
        self.output = np.zeros(self.size)
        self.previous_phase = np.zeros(self.size // 2 + 1)
        self.phase = np.zeros(self.size // 2 + 1)
        self.omega = 2 * np.pi * np.arange(self.size // 2 + 1) / self.size
        self.targets = np.rint(np.arange(len(self.omega)) * self.ratio).astype(int)
        self.valid = self.targets < len(self.omega)

    def __call__(self, audio, sample_rate, **kwargs):
        chunks = []
        for chunk in audio.reshape(-1).reshape(-1, self.hop):
            self.input[:-self.hop] = self.input[self.hop:]
            self.input[-self.hop:] = chunk
            spectrum = np.fft.rfft(self.input * self.window)
            phase = np.angle(spectrum)
            delta = phase - self.previous_phase - self.omega * self.hop
            delta = (delta + np.pi) % (2 * np.pi) - np.pi
            frequency = (self.omega + delta / self.hop) * self.ratio
            self.previous_phase = phase
            magnitude = np.abs(spectrum)[self.valid]
            targets = self.targets[self.valid]
            amplitudes = np.bincount(targets, weights=magnitude,
                                     minlength=len(self.omega))
            weighted = np.bincount(targets, weights=magnitude * frequency[self.valid],
                                   minlength=len(self.omega))
            self.phase += self.hop * np.divide(weighted, amplitudes,
                                               out=np.zeros_like(weighted),
                                               where=amplitudes > 1e-12)
            self.phase %= 2 * np.pi
            shifted = amplitudes * np.exp(1j * self.phase)
            self.output += np.fft.irfft(shifted, n=self.size) * self.window / 1.5
            chunks.append(self.output[:self.hop].copy())
            self.output[:-self.hop] = self.output[self.hop:]
            self.output[-self.hop:] = 0
        return np.concatenate(chunks).astype(np.float32).reshape(1, -1)


def create_voices(mode, sample_rate, block_size):
    if mode == "original":
        return []
    if mode == "chor":
        return [ChorusVoice(sample_rate, block_size, 4.8, 0.8, 0.43, 0.0),
                ChorusVoice(sample_rate, block_size, 6.5, 1.2, 0.61, 1.5),
                ChorusVoice(sample_rate, block_size, 8.5, 1.5, 0.79, 3.0),
                ChorusVoice(sample_rate, block_size, 10.2, 1.8, 0.97, 4.5)]
    # Original + major third + perfect fifth; no reverb.
    return [SpectralVoice(semitones=4), SpectralVoice(semitones=7)]


class VoiceProcessor:
    def __init__(self, mode, block_size, sample_rate=SAMPLE_RATE, output_channels=1):
        self.sample_rate = sample_rate
        self.output_channels = output_channels
        if mode == "chor":
            self.dry_gain = 0.4
            pans = (-0.85, -0.3, 0.3, 0.85)
            self.voice_gains = [np.array([1 - pan, 1 + pan], dtype=np.float32) * 0.15
                                if output_channels == 2 else np.array([0.15], dtype=np.float32)
                                for pan in pans]
        else:
            self.dry_gain = 1 / 3
            self.voice_gains = [np.full(output_channels, 1 / 3, dtype=np.float32)
                                for _ in range(2)]
        self.voices = create_voices(mode, sample_rate, block_size)
        self.block_size = block_size
        effect_delay = self.voices[0].size - self.voices[0].hop if mode == "harmonie" else 0
        self.dry_delay = np.zeros(effect_delay, dtype=np.float32)
        self.overflows = 0
        self.underflows = 0
        self.error = None
        self.max_process_ms = 0.0
        self.deadline_misses = 0
    def process(self, samples):
        if not self.voices:
            return np.repeat(samples, self.output_channels, axis=1)
        audio = np.ascontiguousarray(samples.T)
        dry = np.concatenate((self.dry_delay, samples[:, 0]))
        output = np.repeat(dry[:len(samples), None], self.output_channels, axis=1)
        output *= self.dry_gain
        self.dry_delay = dry[len(samples):]
        for voice, gains in zip(self.voices, self.voice_gains):
            result = voice(audio, self.sample_rate,
                           buffer_size=self.block_size, reset=False)
            output += result.T * gains
        np.clip(output, -1.0, 1.0, out=output)
        return output

    def callback(self, indata, outdata, frames, timing, status):
        self.overflows += int(status.input_overflow)
        self.underflows += int(status.output_underflow)
        started = time.perf_counter()
        try:
            outdata[:] = self.process(indata)
        except Exception as exc:
            outdata.fill(0)
            self.error = exc
            raise sd.CallbackAbort
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.max_process_ms = max(self.max_process_ms, elapsed)
            self.deadline_misses += int(elapsed > frames / self.sample_rate * 1000)


def open_audio_stream(args, devices, input_info, output_info, output_channels):
    candidates = ([args.sample_rate] if args.sample_rate else
                  [input_info["default_samplerate"], output_info["default_samplerate"],
                   48000, 44100, 32000, 16000])
    rates = list(dict.fromkeys(int(rate) for rate in candidates))
    def settings(info):
        api_name = sd.query_hostapis(info["hostapi"])["name"]
        return sd.WasapiSettings(auto_convert=True) if "WASAPI" in api_name else None

    input_settings = settings(input_info)
    output_settings = settings(output_info)
    errors = []
    for rate in rates:
        try:
            sd.check_input_settings(device=devices[0], channels=1,
                                    dtype="float32", samplerate=rate,
                                    extra_settings=input_settings)
            sd.check_output_settings(device=devices[1], channels=output_channels,
                                     dtype="float32", samplerate=rate,
                                     extra_settings=output_settings)
            processor = VoiceProcessor(args.mode, args.block_size, rate, output_channels)
            stream = sd.Stream(samplerate=rate, blocksize=args.block_size,
                               device=devices, channels=(1, output_channels),
                               dtype="float32", latency=args.latency,
                               callback=processor.callback,
                               extra_settings=(input_settings, output_settings))
            return stream, processor, rate
        except sd.PortAudioError as exc:
            # Only retry sample-rate errors; preserve unrelated device errors.
            if len(exc.args) < 2 or exc.args[1] != -9997:
                raise
            errors.append(f"{rate} Hz: {exc}")
    raise sd.PortAudioError(
        "Keine gemeinsame Samplerate gefunden. "
        "Eingang und Ausgang am selben USB-Audiointerface verwenden oder "
        "die Standardformate beider Geraete in Windows angleichen.\n"
        + "\n".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("original", "chor", "harmonie"), default="chor")
    parser.add_argument("--block-size", type=int,
                        help="Default: 256 for speech chorus, 512 for harmony")
    parser.add_argument("--sample-rate", type=int, help="Explicit sample rate; otherwise auto-detect")
    parser.add_argument("--latency", choices=("low", "high"), default="low")
    parser.add_argument("--host-api", default="auto",
                        help="auto, system, WASAPI, MME or another host API name")
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--parent-control", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--seconds", type=float, help="Stop automatically after N seconds")
    args = parser.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return
    if args.block_size is None:
        args.block_size = 512 if args.mode == "harmonie" else 256
    if args.sample_rate is not None and args.sample_rate <= 0:
        parser.error("Sample rate must be positive")
    if args.block_size <= 0 or (args.seconds is not None and args.seconds <= 0):
        parser.error("Block size and duration must be positive")
    if args.mode == "harmonie" and args.block_size % 256:
        parser.error("Harmony block size must be a multiple of 256")

    devices = (args.input_device, args.output_device)
    host_name = args.host_api
    if host_name == "auto":
        host_name = "WASAPI" if sys.platform == "win32" else "system"
    if host_name != "system":
        matches = [api for api in sd.query_hostapis()
                   if host_name.casefold() in api["name"].casefold()]
        if len(matches) != 1:
            parser.error("Audiotreiber nicht eindeutig gefunden: " + host_name)
        api = matches[0]
        devices = (args.input_device if args.input_device is not None
                   else api["default_input_device"],
                   args.output_device if args.output_device is not None
                   else api["default_output_device"])
        if any(device < 0 for device in devices):
            parser.error("Dieser Treiber hat keinen Standard-Eingang oder -Ausgang")
    input_info = sd.query_devices(devices[0], "input")
    output_info = sd.query_devices(devices[1], "output")
    output_channels = min(2, output_info["max_output_channels"])

    print("THE POWER OF ONE -", args.mode)
    if args.mode == "chor":
        print("Sprechchor: 5 Stimmen (Original + vier modulierte Kopien), ohne Hall.")
        print("Zum Vergleich einen Satz langsam sprechen.")
        print("Stereo: Stimmen links/rechts verteilt; Mono: alle zusammengemischt.")
    elif args.mode == "harmonie":
        print("Gesang: Original +4 +7 Halbtoene (fester Dur-Akkord).")
        print("Zum Vergleich einen gleichmaessigen Ton auf 'Ah' halten.")
        print("Keine automatische Anpassung an Tonart oder Melodie.")
    if args.mode == "original":
        print("Original ohne Effekte: Test von Audiotreiber und Geraeten.")
    print("Kabelgebundene Kopfhoerer verwenden. Strg+C beendet.")
    print("Block:", args.block_size, "Samples; Puffer:", args.latency)
    stop_event = threading.Event()
    if args.parent_control:
        # A command or EOF means the camera process has stopped.
        def wait_for_parent():
            sys.stdin.readline()
            stop_event.set()
        threading.Thread(target=wait_for_parent, daemon=True).start()
    processor = None
    try:
        stream, processor, sample_rate = open_audio_stream(
            args, devices, input_info, output_info, output_channels)
        with stream:
            print("Samplerate:", sample_rate, "Hz")
            if args.mode == "harmonie":
                print("FFT-Fenster:", processor.voices[0].size, "Samples; Effektverzoegerung:",
                      round(len(processor.dry_delay) / sample_rate * 1000, 1), "ms")
            print("Geraete:", stream.device)
            print("Eingang:", input_info["name"])
            print("Ausgang:", output_info["name"])
            print("Treiber:", sd.query_hostapis(output_info["hostapi"])["name"])
            print("Ein-/Ausgabelatenz (ms):",
                  tuple(round(value * 1000, 1) for value in stream.latency))
            start = time.monotonic()
            last_status = (0, 0)
            while stream.active and not stop_event.is_set():
                sd.sleep(100)
                if args.seconds is not None and time.monotonic() - start >= args.seconds:
                    break
                status = (processor.overflows, processor.underflows)
                if status != last_status:
                    print("input overflow / output underflow:", status)
                    print("Max. Rechenzeit (ms):", round(processor.max_process_ms, 2),
                          "/ Zeit pro Block:", round(args.block_size / sample_rate * 1000, 2),
                          "; Zeitueberschreitungen:", processor.deadline_misses)
                    last_status = status
        if processor.error is not None:
            raise RuntimeError("Audioverarbeitung fehlgeschlagen") from processor.error
    except KeyboardInterrupt:
        print("Beendet.")
    except sd.PortAudioError as exc:
        parser.exit(1, f"Audiofehler: {exc}\nGeraete mit --list-devices anzeigen.\n")
    if processor is None:
        return
    print("Max. Rechenzeit (ms):", round(processor.max_process_ms, 2),
          "; Zeitueberschreitungen:", processor.deadline_misses)
    print("input overflow / output underflow:",
          (processor.overflows, processor.underflows))


if __name__ == "__main__":
    main()
