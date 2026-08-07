import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from defusedxml import ElementTree as SafeElementTree
from fastapi import HTTPException, UploadFile, status
from pypdf import PdfReader

from career_agent_api.models.enums import FactCategory, SourceKind

MAX_ARCHIVE_ENTRIES = 200
MAX_ARCHIVE_EXPANDED_BYTES = 25_000_000
MAX_ARCHIVE_MEMBER_BYTES = 5_000_000
MAX_EXTRACTED_TEXT_CHARS = 150_000
MAX_FACTS = 200

_PERSONAL_IDENTIFIER_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\bSA\d{22}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\+?966|0)?5\d{8}(?!\d)"),
    re.compile(r"(?<!\d)[12]\d{9}(?!\d)"),
)


@dataclass(frozen=True, slots=True)
class FactCandidate:
    category: FactCategory
    label: str
    detail: str | None
    structured_value: dict[str, str]
    source_excerpt: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ParsedImport:
    source_kind: SourceKind
    parser: str
    candidates: list[FactCandidate]
    extracted_text: str | None = None


def redact_personal_identifiers(value: str) -> str:
    redacted = value
    for pattern in _PERSONAL_IDENTIFIER_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


async def read_limited_upload(upload: UploadFile, max_bytes: int) -> bytes:
    chunks = bytearray()
    while chunk := await upload.read(min(1_048_576, max_bytes + 1 - len(chunks))):
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File exceeds the {max_bytes}-byte import limit",
            )
    if not chunks:
        raise HTTPException(status_code=422, detail="Import file is empty")
    return bytes(chunks)


def _safe_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP container") from exc
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        archive.close()
        raise HTTPException(status_code=422, detail="Archive contains too many files")
    expanded_total = 0
    for entry in entries:
        normalized_name = entry.filename.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        if path.is_absolute() or ".." in path.parts:
            archive.close()
            raise HTTPException(status_code=422, detail="Unsafe archive path")
        if entry.flag_bits & 0x1:
            archive.close()
            raise HTTPException(status_code=422, detail="Encrypted archives are not accepted")
        if entry.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            archive.close()
            raise HTTPException(status_code=422, detail="Archive member is too large")
        expanded_total += entry.file_size
        if expanded_total > MAX_ARCHIVE_EXPANDED_BYTES:
            archive.close()
            raise HTTPException(status_code=422, detail="Expanded archive is too large")
        if entry.file_size and entry.compress_size == 0:
            archive.close()
            raise HTTPException(status_code=422, detail="Suspicious archive compression")
        if entry.compress_size and entry.file_size / entry.compress_size > 100:
            archive.close()
            raise HTTPException(status_code=422, detail="Suspicious archive compression ratio")
    return archive


def _parse_pdf(data: bytes) -> ParsedImport:
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File extension and PDF signature disagree")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise HTTPException(status_code=422, detail="Encrypted PDFs are not accepted")
        if len(reader.pages) > 30:
            raise HTTPException(status_code=422, detail="PDF page limit is 30")
        page_texts: list[str] = []
        extracted_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            extracted_chars += len(page_text) + (1 if page_texts else 0)
            if extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                raise HTTPException(status_code=422, detail="Extracted document text is too large")
            page_texts.append(page_text)
        text = "\n".join(page_texts)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="PDF could not be safely parsed") from exc
    return ParsedImport(
        SourceKind.CV_UPLOAD,
        "pdf-v1",
        _facts_from_cv_text(text),
        extracted_text=text,
    )


def _parse_docx(data: bytes) -> ParsedImport:
    if not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=422, detail="File extension and DOCX signature disagree")
    with _safe_zip(data) as archive:
        names = {entry.filename.replace("\\", "/") for entry in archive.infolist()}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise HTTPException(status_code=422, detail="ZIP file is not a valid DOCX document")
        try:
            root = SafeElementTree.fromstring(archive.read("word/document.xml"))
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail="DOCX XML could not be safely parsed"
            ) from exc
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        text = "".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t"))
        if text.strip():
            paragraphs.append(text.strip())
    extracted_text = "\n".join(paragraphs)
    return ParsedImport(
        SourceKind.CV_UPLOAD,
        "docx-v1",
        _facts_from_cv_text(extracted_text),
        extracted_text=extracted_text,
    )


def _first(row: dict[str, str], *keys: str) -> str:
    folded = {key.casefold().strip(): (value or "").strip() for key, value in row.items() if key}
    for key in keys:
        if value := folded.get(key.casefold()):
            return value
    return ""


def _candidate(
    category: FactCategory,
    label: str,
    detail: str = "",
    structured_value: dict[str, str] | None = None,
) -> FactCandidate | None:
    clean_label = redact_personal_identifiers(label).strip()[:500]
    if not clean_label:
        return None
    clean_detail = redact_personal_identifiers(detail).strip()[:4000] or None
    values = {
        key: redact_personal_identifiers(value)[:1000]
        for key, value in (structured_value or {}).items()
        if value
    }
    excerpt = " | ".join(filter(None, (clean_label, clean_detail or "")))[:4000]
    return FactCandidate(category, clean_label, clean_detail, values, excerpt, 0.95)


def _parse_linkedin_zip(data: bytes) -> ParsedImport:
    if not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=422, detail="File extension and ZIP signature disagree")
    candidates: list[FactCandidate] = []
    with _safe_zip(data) as archive:
        entries = {
            PurePosixPath(entry.filename.replace("\\", "/")).name.casefold(): entry
            for entry in archive.infolist()
            if not entry.is_dir()
        }
        supported = {
            "profile.csv",
            "positions.csv",
            "education.csv",
            "certifications.csv",
            "skills.csv",
            "languages.csv",
            "projects.csv",
        }
        if not set(entries) & supported:
            raise HTTPException(
                status_code=422,
                detail="ZIP does not contain supported LinkedIn export files",
            )
        for filename in sorted(set(entries) & supported):
            try:
                decoded = archive.read(entries[filename]).decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(decoded)))[:500]
            except (UnicodeDecodeError, csv.Error) as exc:
                raise HTTPException(status_code=422, detail=f"Could not parse {filename}") from exc
            for row in rows:
                candidate = _linkedin_row_candidate(filename, row)
                if candidate:
                    candidates.append(candidate)
                if len(candidates) >= MAX_FACTS:
                    break
    return ParsedImport(
        SourceKind.LINKEDIN_EXPORT,
        "linkedin-export-v1",
        _deduplicate(candidates),
    )


def _linkedin_row_candidate(filename: str, row: dict[str, str]) -> FactCandidate | None:
    if filename == "skills.csv":
        return _candidate(FactCategory.SKILL, _first(row, "Name", "Skill Name"))
    if filename == "languages.csv":
        name = _first(row, "Name", "Language")
        proficiency = _first(row, "Proficiency")
        return _candidate(
            FactCategory.LANGUAGE,
            name,
            proficiency,
            {"proficiency": proficiency},
        )
    if filename == "positions.csv":
        title = _first(row, "Title")
        company = _first(row, "Company Name", "Company")
        description = _first(row, "Description")
        return _candidate(
            FactCategory.EXPERIENCE,
            title,
            description,
            {
                "company": company,
                "started_on": _first(row, "Started On"),
                "finished_on": _first(row, "Finished On"),
            },
        )
    if filename == "education.csv":
        school = _first(row, "School Name", "School")
        degree = _first(row, "Degree Name", "Degree")
        return _candidate(
            FactCategory.EDUCATION,
            degree or school,
            _first(row, "Notes", "Activities"),
            {"school": school, "field": _first(row, "Field Of Study")},
        )
    if filename == "certifications.csv":
        name = _first(row, "Name")
        return _candidate(
            FactCategory.CERTIFICATION,
            name,
            "",
            {"authority": _first(row, "Authority"), "url": _first(row, "Url")},
        )
    if filename == "projects.csv":
        return _candidate(
            FactCategory.PROJECT,
            _first(row, "Title", "Name"),
            _first(row, "Description"),
            {"url": _first(row, "Url")},
        )
    if filename == "profile.csv":
        headline = _first(row, "Headline")
        summary = _first(row, "Summary")
        return _candidate(FactCategory.IDENTITY, headline, summary)
    return None


def _facts_from_cv_text(text: str) -> list[FactCandidate]:
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise HTTPException(status_code=422, detail="Extracted document text is too large")
    category_cues = {
        FactCategory.EDUCATION: (
            "bachelor",
            "degree",
            "diploma",
            "university",
            "بكالوريوس",
            "دبلوم",
            "جامعة",
            "التعليم",
            "المؤهلات",
        ),
        FactCategory.CERTIFICATION: (
            "certificate",
            "certification",
            "certified",
            "شهادة",
            "الشهادات",
        ),
        FactCategory.EXPERIENCE: (
            "experience",
            "employment",
            "work history",
            "خبرة",
            "الخبرات",
        ),
        FactCategory.PROJECT: ("project", "مشروع", "المشاريع"),
        FactCategory.LANGUAGE: (
            "language",
            "english",
            "arabic",
            "لغة",
            "اللغات",
            "العربية",
            "الإنجليزية",
        ),
        FactCategory.ACHIEVEMENT: (
            "achievement",
            "award",
            "إنجاز",
            "جائزة",
            "الإنجازات",
        ),
    }
    known_skills = (
        "python",
        "typescript",
        "javascript",
        "react",
        "next.js",
        "fastapi",
        "sql",
        "postgresql",
        "figma",
        "docker",
        "git",
    )
    candidates: list[FactCandidate] = []
    for raw_line in text.splitlines():
        line = redact_personal_identifiers(
            " ".join(raw_line.split()).strip("-•* \t")
        )
        if not 2 <= len(line) <= 1000:
            continue
        lowered = line.casefold()
        if any(
            _contains_atomic_term(lowered, skill) and _unsafe_skill_attribution(lowered, skill)
            for skill in known_skills
        ):
            # Do not emit a broader EXPERIENCE/PROJECT fact for the same sentence: matching may
            # otherwise reuse that fact as positive skill evidence.
            continue
        for skill in known_skills:
            if _contains_atomic_term(lowered, skill):
                candidates.append(
                    FactCandidate(
                        FactCategory.SKILL,
                        skill,
                        None,
                        {},
                        line[:4000],
                        0.8,
                    )
                )
        for category, cues in category_cues.items():
            if any(cue in lowered for cue in cues):
                candidates.append(FactCandidate(category, line[:500], None, {}, line[:4000], 0.65))
                break
        if len(candidates) >= MAX_FACTS:
            break
    return _deduplicate(candidates)


def _unsafe_skill_attribution(line: str, skill: str) -> bool:
    """Reject negated or clearly third-party skill statements.

    CV extraction is only a candidate generator, but even an unconfirmed positive candidate can
    prime a user into accepting a false claim. Ambiguity therefore fails closed.
    """

    escaped_skill = re.escape(skill)
    negation_patterns = (
        rf"\b(?:no|not|never|without|cannot|can['’]?t|(?:did|do|does|is|was|were|have|has)n['’]?t|"
        rf"lack(?:s|ed|ing)?)\b.{{0,50}}\b{escaped_skill}\b",
        rf"\b{escaped_skill}\b.{{0,50}}\b(?:not|never|without|lack(?:s|ed|ing)?)\b",
        rf"(?<!\w)(?:لا|لم|لن|ليس|لست|بدون|دون|غير)(?!\w)"
        rf".{{0,50}}{escaped_skill}",
        rf"{escaped_skill}.{{0,50}}(?<!\w)(?:غير متقن|لا أجيد|لا أملك)(?!\w)",
    )
    third_party_patterns = (
        rf"\b(?:he|she|they|my\s+team|the\s+team|manager|colleague|coworker|client)\b"
        rf".{{0,60}}\b{escaped_skill}\b",
        rf"(?<!\w)(?:فريق(?:ي)?|زميلي|زميلتي|مديري|العميل)(?!\w)"
        rf".{{0,60}}{escaped_skill}",
    )
    return any(
        re.search(pattern, line, flags=re.IGNORECASE)
        for pattern in (*negation_patterns, *third_party_patterns)
    )


def _contains_atomic_term(value: str, term: str) -> bool:
    return bool(
        re.search(
            rf"(?<![\w.+#-]){re.escape(term)}(?![\w.+#-])",
            value,
            flags=re.IGNORECASE,
        )
    )


def _deduplicate(candidates: list[FactCandidate]) -> list[FactCandidate]:
    unique: list[FactCandidate] = []
    seen: set[tuple[str, str, str | None]] = set()
    for candidate in candidates:
        key = (candidate.category.value, candidate.label.casefold(), candidate.detail)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique[:MAX_FACTS]


def parse_import(filename: str, content_type: str | None, data: bytes) -> ParsedImport:
    lowered_name = filename.casefold()
    declared_type = (content_type or "application/octet-stream").casefold()
    if lowered_name.endswith(".pdf"):
        if declared_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=422, detail="Unsupported PDF content type")
        return _parse_pdf(data)
    if lowered_name.endswith(".docx"):
        if declared_type not in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
            "application/octet-stream",
        }:
            raise HTTPException(status_code=422, detail="Unsupported DOCX content type")
        return _parse_docx(data)
    if lowered_name.endswith(".zip"):
        if declared_type not in {
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
        }:
            raise HTTPException(status_code=422, detail="Unsupported ZIP content type")
        return _parse_linkedin_zip(data)
    raise HTTPException(status_code=422, detail="Only PDF, DOCX, and LinkedIn ZIP are accepted")


def metadata_for_import(data: bytes, parsed: ParsedImport) -> dict[str, object]:
    from hashlib import sha256

    return {
        "content_sha256": sha256(data).hexdigest(),
        "size_bytes": len(data),
        "parser": parsed.parser,
        "candidate_fact_count": len(parsed.candidates),
        "raw_file_retained": False,
        "professional_data_only": True,
    }
