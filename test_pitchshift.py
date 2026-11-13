from pedalboard import Pedalboard, PitchShift
from pedalboard.io import AudioStream
# None verwendet die unten ausdrücklich ermittelten Windows-Standardgeräte.
# Alternativ hier einen Gerätenamen aus AudioStream.input_device_names
# beziehungsweise AudioStream.output_device_names eintragen.
INPUT_DEVICE = None
OUTPUT_DEVICE = None

def main():
    # Nur EIN Effekt:
    # Stimme wird um 3 Halbtöne nach oben verschoben.
    board = Pedalboard([
        PitchShift(semitones=3)
    ])

    print()
    print("====================================")
    print(" Pedalboard PitchShift Test")
    print("====================================")
    print()
    print("PitchShift: +3 Halbtöne")
    print("Sprich z.B.: Ta! Ta! Ta!")
    print()
    print("Enter beendet das Programm.")
    print()

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
        ) as stream:

            # Alles, was vom Mikrofon kommt,
            # wird durch unser Pedalboard geschickt.
            stream.plugins = board

            # Das Programm läuft weiter,
            # bis Enter gedrückt wird.
            input()

    except Exception as error:
        print()
        print("FEHLER:")
        print(error)
        print()
        print(
            "Prüfe, ob Mikrofon und Kopfhörer "
            "unter Windows als Standardgeräte eingestellt sind."
        )


if __name__ == "__main__":
    main()