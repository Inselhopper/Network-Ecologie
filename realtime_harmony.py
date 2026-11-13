from pedalboard import (
    Pedalboard,
    Mix,
    PitchShift,
    Gain,
    Compressor,
    Limiter,
    Reverb,
)
from pedalboard.io import AudioStream


# None verwendet die unten ausdrücklich ermittelten Windows-Standardgeräte.
# Alternativ hier einen Gerätenamen aus AudioStream.input_device_names
# beziehungsweise AudioStream.output_device_names eintragen.
INPUT_DEVICE = None
OUTPUT_DEVICE = None


def create_harmony_board() -> Pedalboard:
    original_voice = Pedalboard([
        Gain(gain_db=-4.0),
    ])

    third_voice = Pedalboard([
        PitchShift(semitones=4),   # große Terz höher
        Gain(gain_db=-9.0),
    ])

    fifth_voice = Pedalboard([
        PitchShift(semitones=7),   # Quinte höher
        Gain(gain_db=-11.0),
    ])

    return Pedalboard([
        # Lautstärkeunterschiede der Stimme etwas ausgleichen
        Compressor(
            threshold_db=-24,
            ratio=3,
        ),

        # Drei Stimmen parallel mischen
        Mix([
            original_voice,
            third_voice,
            fifth_voice,
        ]),

        # Nur wenig Raumklang
        Reverb(
            room_size=0.15,
            wet_level=0.08,
            dry_level=0.92,
        ),

        # Schutz vor Übersteuerung
        Limiter(
            threshold_db=-1.0,
        ),
    ])


def main() -> None:
    harmony_board = create_harmony_board()

    print("Echtzeit-Harmonie wird gestartet.")
    print("Bitte Kopfhörer verwenden, sonst entsteht Rückkopplung.")
    print("Zum Beenden Enter drücken.")

    try:
        input_device = INPUT_DEVICE or AudioStream.default_input_device_name
        output_device = OUTPUT_DEVICE or AudioStream.default_output_device_name

        if not input_device or not output_device:
            raise RuntimeError(
                "Es werden ein Mikrofon und ein Ausgabegerät benötigt.\n"
                f"Verfügbare Eingänge: {AudioStream.input_device_names}\n"
                f"Verfügbare Ausgänge: {AudioStream.output_device_names}"
            )

        print(f"Mikrofon: {input_device}")
        print(f"Audioausgabe: {output_device}")

        with AudioStream(
            input_device_name=input_device,
            output_device_name=output_device,
            plugins=harmony_board,
        ) as stream:
            print(
                f"Audiopuffer: {stream.buffer_size} Samples "
                f"bei {stream.sample_rate:g} Hz "
                f"({1000 * stream.buffer_size / stream.sample_rate:.1f} ms pro Puffer; "
                "Gesamtverzögerung ist höher)."
            )
            input()

    except Exception as error:
        print("\nAudiostream konnte nicht gestartet werden:")
        print(error)
        print(
            "\nPrüfe, ob Mikrofon und Audioausgabe als "
            "Windows-Standardgeräte eingestellt sind."
        )


if __name__ == "__main__":
    main()
