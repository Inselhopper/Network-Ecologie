"""Hardware-free regression checks for the actual installation controller."""
import queue
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from network_ecologie import Installation, prepare, mouth_angle


class FakeAudio:
    rate = 1000
    def __init__(self):
        self.events, self.statuses = queue.Queue(), deque()
        self.data = np.zeros(0)
        self.done, self.clock = False, 0
    def listen(self, enabled):
        self.accept = enabled
        while not self.events.empty():
            self.events.get_nowait()
    def stop(self):
        self.data = np.zeros(0)
    def play(self, data):
        self.listen(False)
        self.data, self.done, self.clock = data, False, 0
    def elapsed(self):
        return self.clock
    def finished(self):
        return self.done


def run():
    audio = FakeAudio()
    args = SimpleNamespace(threshold=.025, mouth_threshold=.12, max_record=1,
                           silence=.2, together_seconds=1, response_window=1)
    now = [10.0]
    with patch("network_ecologie.time.perf_counter", side_effect=lambda: now[0]):
        machine = Installation(audio, args)
        try:
            audio.events.put((10., np.full(100, .2, dtype=np.float32)))
            machine.update(.5)
            assert machine.state == "RECORDING_HUMAN"
            assert machine.angle == 35, "servo must rest while recording"
            now[0] = 10.5
            audio.events.put((10.5, np.zeros(100, dtype=np.float32)))
            machine.update(.5)
            assert machine.state in ("PROCESSING_RESPONSE", "PLAYBACK_RESPONSE")
            if machine.future is not None:
                machine.future.result(timeout=3)
                machine.update(.5)
            assert machine.state == "PLAYBACK_RESPONSE" and not audio.accept
            audio.clock = .1
            machine.update(.5)
            assert machine.source == "Aufgezeichnetes FaceMesh"
            audio.done = True
            machine.update(0)
            assert machine.state == "INVITATION_PAUSE"
            now[0] += 2
            machine.update(0)
            assert machine.state == "WAITING_FOR_RESPONSE" and audio.accept
            machine.update(.4)
            assert machine.state == "SYNCHRONOUS_PLAY" and not audio.accept
            machine.update(.5)
            assert machine.source == "FaceMesh live"
            audio.done = True
            machine.update(.5)
            assert machine.state == "MACHINE_LEADS"
            machine.update(.6)
            assert machine.source == "Maschinenklang"
            audio.done = True
            machine.update(0)
            assert machine.state == "HUMAN_JOINS"
            machine.update(.5)
            assert machine.joined
            audio.done = True
            machine.update(0)
            assert machine.state == "FADE_OUT"
            now[0] += 3
            machine.update(0)
            assert machine.state == "LISTENING"
            assert machine.response is None and not machine.motion
            machine.transition("WAITING_FOR_RESPONSE")
            now[0] += 2
            machine.update(0)
            assert machine.state == "FADE_OUT", "unanswered invitation must end"
            assert 35 <= machine.angle <= 95
        finally:
            machine.close()
    source = np.sin(np.arange(2000) * .1).astype(np.float32)
    response, phrase = prepare(source, 1000)
    assert len(response) == len(source)
    assert np.max(np.abs(response)) <= .9
    assert np.all(np.isfinite(phrase)) and len(phrase) > 0
    assert mouth_angle(-1) == 35 and mouth_angle(10) == 95
    print("OK: recording, playback, invitation, together, machine leadership, reset, bounds")


if __name__ == "__main__":
    run()
