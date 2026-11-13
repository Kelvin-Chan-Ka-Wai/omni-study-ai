"""Study-data backups exclude credentials, browser profiles and server logs."""
import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from database import DB_PATH, STORAGE_DIR, engine, init_db

router = APIRouter(prefix='/api/backup', tags=['Study-data backup'])


def make_backup():
    output = io.BytesIO()
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / 'study_history.db'
        with sqlite3.connect(DB_PATH) as source, sqlite3.connect(snapshot) as destination: source.backup(destination)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, 'study_history.db')
            for folder in ('uploads', 'handwritten_snaps'):
                for file in (STORAGE_DIR / folder).glob('*'):
                    if file.is_file() and not file.is_symlink() and file.name != '.gitkeep': archive.write(file, folder + '/' + file.name)
    return output.getvalue()


@router.get('')
def download_backup():
    return Response(make_backup(), media_type='application/zip', headers={'Content-Disposition':'attachment; filename="omnistudy-study-backup.zip"'})


@router.post('/restore')
async def restore_backup(backup: UploadFile = File(...)):
    from routers.jobs import tasks
    if tasks: raise HTTPException(409, 'Finish or cancel generation before restoring')
    data = await backup.read(250 * 1024 * 1024 + 1)
    if len(data) > 250 * 1024 * 1024: raise HTTPException(400, 'Backup must be smaller than 250 MB')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if sum(e.file_size for e in entries) > 1024 * 1024 * 1024: raise ValueError()
        for entry in entries:
            path = Path(entry.filename)
            if entry.is_dir() or path.is_absolute() or '..' in path.parts or not (entry.filename == 'study_history.db' or len(path.parts) == 2 and path.parts[0] in ('uploads','handwritten_snaps')):
                raise ValueError()
        with tempfile.TemporaryDirectory() as directory:
            archive.extractall(directory)
            source_db = Path(directory) / 'study_history.db'
            with sqlite3.connect(source_db) as source:
                if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError()
                tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'chapters','chapter_sections','exam_sessions','question_records','wrong_question_bank'} <= tables: raise ValueError()
            # Save a reversible snapshot before replacing any study data. Credentials are never involved.
            from datetime import datetime
            before = STORAGE_DIR / 'backups' / ('before-restore-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')
            before.parent.mkdir(exist_ok=True)
            before.write_bytes(make_backup()); before.chmod(0o600)
            engine.dispose()
            with sqlite3.connect(source_db) as source, sqlite3.connect(DB_PATH) as target: source.backup(target)
            for folder in ('uploads','handwritten_snaps'):
                for file in (Path(directory)/folder).glob('*'):
                    (STORAGE_DIR/folder/file.name).write_bytes(file.read_bytes())
            init_db()
        return {'restored': True}
    except (ValueError, zipfile.BadZipFile, sqlite3.DatabaseError, KeyError):
        raise HTTPException(400, 'Invalid or unsupported study backup')
