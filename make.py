import ctypes
import os
import platform
import re
import shutil
import zipfile
from pathlib import Path


RELEASE_PLUGIN_DIRECTORY = 'crs_magic_finder'
EXCLUDED_DIRS = {'.git', '.codex', '__TestData', '.vscode', '__sources', '__pycache__', '.agents'}
EXCLUDED_FILES = {'.gitignore', 'make.py'}


def get_desktop_path():
    system = platform.system()
    if system == 'Windows':
        try:
            path = ctypes.create_unicode_buffer(512)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, path)
            return Path(path.value)
        except Exception as error:
            print(f'Error retrieving desktop path on Windows: {error}')
            return Path(os.environ['USERPROFILE']) / 'Desktop'
    if system == 'Linux':
        return Path.home() / 'Desktop'
    raise NotImplementedError(f'Unsupported OS: {system}')


def metadata_value(metadata_text, key):
    match = re.search(rf'^{re.escape(key)}=(.*)$', metadata_text, re.MULTILINE)
    return match.group(1).strip() if match else ''


def release_metadata(metadata_text):
    pattern = re.compile(r'^(name\s*=\s*)(.*?)(\s*)$', re.MULTILINE)
    match = pattern.search(metadata_text)
    if not match:
        raise ValueError('metadata.txt does not contain name=')

    display_name = match.group(2).rstrip()
    if not display_name.casefold().endswith(' dev'):
        raise ValueError('The development plugin name must end with DEV')
    release_name = display_name[:-4].rstrip()
    return pattern.sub(
        lambda item: f'{item.group(1)}{release_name}{item.group(3)}',
        metadata_text,
        count=1,
    )


def prepare_runtime_files(source_directory):
    initial_source = source_directory / '__sources' / 'initial_crs_sets'
    initial_target = source_directory / 'initial_crs_sets'
    if initial_source.is_dir():
        shutil.copytree(initial_source, initial_target, dirs_exist_ok=True)


def write_plugin_archive(source_directory, archive_path):
    metadata_path = source_directory / 'metadata.txt'
    metadata_text = metadata_path.read_text(encoding='utf-8-sig')
    packaged_metadata = release_metadata(metadata_text).encode('utf-8')

    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(source_directory):
            dirs[:] = sorted(directory for directory in dirs if directory not in EXCLUDED_DIRS)
            for file_name in sorted(files):
                if file_name in EXCLUDED_FILES or file_name.endswith('~'):
                    continue
                file_path = Path(root) / file_name
                relative_path = file_path.relative_to(source_directory)
                archive_name = (Path(RELEASE_PLUGIN_DIRECTORY) / relative_path).as_posix()
                if relative_path.as_posix() == 'metadata.txt':
                    archive.writestr(archive_name, packaged_metadata)
                else:
                    archive.write(file_path, archive_name)


def main():
    source_directory = Path(__file__).resolve().parent
    metadata_text = (source_directory / 'metadata.txt').read_text(encoding='utf-8-sig')
    version = metadata_value(metadata_text, 'version')
    if not version:
        raise ValueError('metadata.txt does not contain version=')

    prepare_runtime_files(source_directory)
    desktop_directory = get_desktop_path()
    if not desktop_directory.is_dir():
        raise FileNotFoundError(f'Desktop path does not exist: {desktop_directory}')

    archive_path = desktop_directory / f'{RELEASE_PLUGIN_DIRECTORY}_{version}.zip'
    write_plugin_archive(source_directory, archive_path)
    print(f'Created {archive_path}')


if __name__ == '__main__':
    main()
