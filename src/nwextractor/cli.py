"""CLI entry point for NWExtractor."""

import click
from pathlib import Path

from nwextractor.pak.extractor import PakExtractor


@click.group()
@click.version_option()
def main():
    """NWExtractor - Extract and convert New World assets for UE5."""
    pass


@main.command()
@click.option("--game-dir", required=True, type=click.Path(exists=True, path_type=Path), help="Path to New World game directory (containing assets/ folder)")
@click.option("--output", "-o", required=True, type=click.Path(path_type=Path), help="Output directory for extracted files")
@click.option("--filter", "-f", "file_filter", default=None, help="Glob pattern to filter files (e.g. '*.cgf,*.dds')")
@click.option("--oodle-dll", default=None, type=click.Path(path_type=Path), help="Path to oo2core_8_win64.dll (auto-detected from game dir if not specified)")
@click.option("--threads", "-t", default=4, type=int, help="Number of parallel extraction workers")
@click.option("--dry-run", is_flag=True, help="List files without extracting")
def extract(game_dir: Path, output: Path, file_filter: str | None, oodle_dll: Path | None, threads: int, dry_run: bool):
    """Extract raw files from New World .pak archives."""
    assets_dir = game_dir / "assets"
    if not assets_dir.exists():
        assets_dir = game_dir  # Allow pointing directly at assets folder

    # Find oodle DLL
    if oodle_dll is None:
        candidates = list(game_dir.rglob("oo2core_8_win64.dll"))
        if candidates:
            oodle_dll = candidates[0]
            click.echo(f"Found Oodle DLL: {oodle_dll}")
        else:
            click.echo("Error: Could not find oo2core_8_win64.dll. Use --oodle-dll to specify.", err=True)
            raise SystemExit(1)

    # Parse filter patterns
    patterns = None
    if file_filter:
        patterns = [p.strip() for p in file_filter.split(",")]

    # Find all .pak files
    pak_files = sorted(assets_dir.rglob("*.pak"))
    if not pak_files:
        click.echo(f"No .pak files found in {assets_dir}", err=True)
        raise SystemExit(1)

    click.echo(f"Found {len(pak_files)} .pak files")

    extractor = PakExtractor(oodle_dll=oodle_dll)

    total_files = 0
    for pak_path in pak_files:
        click.echo(f"\nProcessing: {pak_path.name}")
        try:
            count = extractor.extract_pak(pak_path, output, patterns=patterns, dry_run=dry_run)
            total_files += count
        except Exception as e:
            click.echo(f"  Error: {e}", err=True)

    action = "Listed" if dry_run else "Extracted"
    click.echo(f"\n{action} {total_files} files total.")


@main.command()
@click.option("--input", "-i", "input_dir", required=True, type=click.Path(exists=True, path_type=Path), help="Directory of extracted raw files")
@click.option("--output", "-o", required=True, type=click.Path(path_type=Path), help="Output directory for converted UE5-ready files")
@click.option("--only", type=click.Choice(["textures", "models", "animations", "materials", "maps"]), help="Convert only a specific asset type")
def convert(input_dir: Path, output: Path, only: str | None):
    """Convert extracted files to UE5-ready formats."""
    click.echo("Convert command - not yet implemented (Phase 2+)")
    click.echo(f"  Input:  {input_dir}")
    click.echo(f"  Output: {output}")
    if only:
        click.echo(f"  Only:   {only}")


@main.command()
@click.option("--game-dir", required=True, type=click.Path(exists=True, path_type=Path), help="Path to New World game directory")
@click.option("--output", "-o", required=True, type=click.Path(path_type=Path), help="Output directory for UE5-ready files")
@click.option("--oodle-dll", default=None, type=click.Path(path_type=Path), help="Path to oo2core_8_win64.dll")
def pipeline(game_dir: Path, output: Path, oodle_dll: Path | None):
    """Full pipeline: extract + convert in one step."""
    click.echo("Pipeline command - not yet implemented")
