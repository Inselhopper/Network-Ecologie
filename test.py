import numpy as np
import sounddevice as sd


# ============================================================
# EINSTELLUNGEN
# ============================================================

SAMPLE_RATE = 48000

# Klein = wenig Latenz
BLOCK_SIZE = 256

# gewünschte Tonhöhenänderung
SEMITONES = 3

# Umrechnung Halbtöne -> Geschwindigkeitsfaktor
PITCH_RATIO = 2 ** (SEMITONES / 12.0)

# Länge unserer Delay-Line
BUFFER_SIZE = 4096


# ============================================================
# PITCH SHIFTER
# ============================================================

buffer = np.zeros(BUFFER_SIZE, dtype=np.float32)

write_pos = 0
read_pos = 0.0


def pitch_shift_sample(sample):
    global write_pos
    global read_pos

    # Neues Mikrofonsample in Ringpuffer schreiben
    buffer[write_pos] = sample

    # Zwei benachbarte Samples lesen
    pos1 = int(read_pos) % BUFFER_SIZE
    pos2 = (pos1 + 1) % BUFFER_SIZE

    fraction = read_pos - int(read_pos)

    # lineare Interpolation
    output = (
        buffer[pos1] * (1.0 - fraction)
        + buffer[pos2] * fraction
    )

    # Schreibposition weiterbewegen
    write_pos = (write_pos + 1) % BUFFER_SIZE

    # Leseposition mit anderer Geschwindigkeit bewegen
    read_pos += PITCH_RATIO

    if read_pos >= BUFFER_SIZE:
        read_pos -= BUFFER_SIZE

    return output


# ============================================================
# AUDIO CALLBACK
# ============================================================

def callback(indata, outdata, frames, time, status):

    if status:
        print(status)

    for i in range(frames):

        input_sample = indata[i, 0]

        shifted = pitch_shift_sample(input_sample)

        outdata[i, 0] = shifted


# ============================================================
# START
# ============================================================

print()
print("======================================")
print(" LOW LATENCY PITCH TEST")
print("======================================")
print()

print("Samplerate :", SAMPLE_RATE)
print("Blockgröße :", BLOCK_SIZE)
print("Pitch      :", SEMITONES, "Halbtöne")

block_latency = BLOCK_SIZE / SAMPLE_RATE * 1000

print(
    "Ein Audio-Block:",
    round(block_latency, 2),
    "ms"
)

print()
print("Kabelgebundene Kopfhörer verwenden!")
print()
print("Sprich:")
print()
print("TA!  TA!  TA!")
print()
print("Strg+C beendet.")
print()


try:

    with sd.Stream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,

        channels=1,

        dtype="float32",

        latency="low",

        callback=callback
    ):

        while True:
            sd.sleep(1000)


except KeyboardInterrupt:

    print()
    print("Beendet.")