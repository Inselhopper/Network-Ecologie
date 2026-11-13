import numpy as np
import sounddevice as sd
import rubband


SAMPLE_RATE = 48000
CHANNELS = 1

# +3 Halbtöne
SEMITONES = 3

# Umrechnung:
# +12 Halbtöne = Faktor 2
PITCH_SCALE = 2 ** (SEMITONES / 12)


# Live-Pitch-Shifter erzeugen
shifter = rubband.LiveShifter(
    SAMPLE_RATE,
    CHANNELS
)

# Rubber Band bestimmt selbst,
# wie groß ein Audio-Block sein muss.
BLOCK_SIZE = shifter.get_block_size()

# Tonhöhe einstellen
shifter.set_pitch_scale(PITCH_SCALE)


print("--------------------------------")
print("Rubber Band Live Pitch Test")
print("--------------------------------")
print()
print(f"Samplerate:   {SAMPLE_RATE}")
print(f"Blockgröße:   {BLOCK_SIZE}")
print(f"Pitch:        +{SEMITONES} Halbtöne")
print()
print("Sprich: Ta! Ta! Ta!")
print("Strg+C beendet das Programm.")
print()


def audio_callback(indata, outdata, frames, time, status):

    if status:
        print(status)

    # sounddevice liefert:
    #
    # (frames, channels)
    #
    # Rubber Band akzeptiert genau dieses Format.
    audio = np.ascontiguousarray(
        indata,
        dtype=np.float32
    )

    # Tonhöhe verändern
    shifted = shifter.shift(audio)

    # AudioBuffer -> NumPy
    shifted_audio = shifted.numpy()

    # zum Kopfhörer schicken
    outdata[:] = shifted_audio


try:

    with sd.Stream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_callback,
        latency="low"
    ):

        print("Audio läuft.")
        print()

        while True:
            sd.sleep(1000)


except KeyboardInterrupt:

    print()
    print("Beendet.")