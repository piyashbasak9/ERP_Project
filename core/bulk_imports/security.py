from io import BytesIO
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_ZIP_ENTRIES = 200
MAX_COMPRESSION_RATIO = 100


def validate_xlsx_archive(upload_bytes, filename):
    if not filename.lower().endswith(".xlsx") or filename.lower().endswith(".xlsm"):
        raise ValidationError("Upload an .xlsx workbook; macro-enabled files are rejected.")
    if len(upload_bytes) > MAX_FILE_BYTES:
        raise ValidationError("Workbook exceeds the 10 MB upload limit.")
    if not upload_bytes.startswith(b"PK\x03\x04"):
        raise ValidationError("The uploaded file is not a valid .xlsx ZIP container.")
    try:
        with ZipFile(BytesIO(upload_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ValidationError("Workbook contains too many compressed entries.")
            if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError("Workbook expands beyond the safe uncompressed size.")
            for entry in entries:
                if entry.file_size and (
                    entry.file_size / max(entry.compress_size, 1)
                    > MAX_COMPRESSION_RATIO
                ):
                    raise ValidationError("Workbook compression ratio is unsafe.")
                if entry.filename.lower().endswith("vbaproject.bin"):
                    raise ValidationError("Macro-enabled workbooks are not accepted.")
                if entry.filename.startswith("xl/externalLinks/"):
                    raise ValidationError("Workbooks with external links are not accepted.")
            if "[Content_Types].xml" not in archive.namelist():
                raise ValidationError("The ZIP file is not an Office Open XML workbook.")
            for entry in entries:
                if entry.filename.endswith(".rels"):
                    root = ElementTree.fromstring(archive.read(entry))
                    if any(
                        value.lower() == "external"
                        for element in root.iter()
                        for attribute, value in element.attrib.items()
                        if attribute.endswith("}TargetMode")
                    ):
                        raise ValidationError(
                            "Workbooks with external links are not accepted."
                        )
    except (BadZipFile, ParseError, RuntimeError) as exc:
        raise ValidationError("The uploaded file is not a valid .xlsx workbook.") from exc


def safe_report_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text
