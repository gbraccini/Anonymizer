import pytest

from anonymizer.cli import main


def test_plain_text_cli_end_to_end(tmp_path):
    source = tmp_path / "source.txt"
    output = tmp_path / "output.txt"
    mapping = tmp_path / "output.map.json"
    restored = tmp_path / "restored.txt"
    source.write_text("Elvio Veltrani; Hb 12 g/dL; non febbre", encoding="utf-8")
    assert main(["anon", str(source), "--output", str(output), "--map", str(mapping)]) == 0
    assert output.read_text("utf-8") == "[[PERSONA_1]]; Hb 12 g/dL; non febbre"
    assert "Veltrani" not in output.read_text("utf-8")
    assert main(["reassoc", str(output), "--map", str(mapping), "--output", str(restored)]) == 0
    assert restored.read_text("utf-8") == source.read_text("utf-8")


def test_cli_error_does_not_print_sensitive_input_or_path(tmp_path, capsys):
    missing = tmp_path / "sensitive-person.txt"
    assert (
        main(
            [
                "anon",
                str(missing),
                "--output",
                str(tmp_path / "out"),
                "--map",
                str(tmp_path / "map"),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "sensitive-person" not in captured.err


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_cli_preserves_exact_line_endings(tmp_path, newline):
    source = tmp_path / "source.txt"
    output = tmp_path / "output.txt"
    mapping = tmp_path / "map.json"
    restored = tmp_path / "restored.txt"
    original = f"😀 Elvio Veltrani{newline}Hb 12 g/dL{newline}Non febbre{newline}".encode()
    source.write_bytes(original)
    assert main(["anon", str(source), "--output", str(output), "--map", str(mapping)]) == 0
    assert output.read_bytes() == original.replace(b"Elvio Veltrani", b"[[PERSONA_1]]")
    assert main(["reassoc", str(output), "--map", str(mapping), "--output", str(restored)]) == 0
    assert restored.read_bytes() == original
