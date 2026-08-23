"""Build a clean résumé (markdown) from a user's structured profile.

Deterministic — needs no AI key, and never fabricates facts. It simply formats
whatever the user has entered. Per-job AI tailoring happens separately in
app/ai/prompts.tailor_resume once the user has a base résumé.
"""

from __future__ import annotations

from typing import Any


def has_minimum_content(profile: Any) -> bool:
    """True when there is enough on the profile to produce a usable résumé.

    Without this a user with an empty profile gets a document containing only
    the placeholder heading, which would then be attached to real applications.
    """
    has_name = bool(
        (getattr(profile, "first_name", None) or "").strip()
        or (getattr(profile, "last_name", None) or "").strip()
    )
    has_substance = any(
        [
            bool(getattr(profile, "work_history", None)),
            bool(getattr(profile, "education", None)),
            bool(getattr(profile, "certifications", None)),
            bool(getattr(profile, "skills", None)),
            bool((getattr(profile, "summary", None) or "").strip()),
        ]
    )
    return has_name and has_substance


def _join(parts: list[Any], sep: str = " · ") -> str:
    return sep.join(str(p).strip() for p in parts if p and str(p).strip())


def build_markdown(profile: Any) -> str:
    name = _join([profile.first_name, profile.last_name], " ") or "Your Name"
    contact_email = getattr(profile, "email", None)
    lines: list[str] = [f"# {name}"]

    contact = _join(
        [
            contact_email,
            profile.phone,
            _join([profile.city, profile.country], ", "),
            profile.postal_code,
        ]
    )
    if contact:
        lines.append(contact)
    if profile.headline:
        lines.append(f"\n**{profile.headline}**")

    if profile.summary:
        lines += ["\n## Summary", profile.summary]

    if profile.skills:
        lines += ["\n## Skills", ", ".join(profile.skills)]

    if profile.work_history:
        lines.append("\n## Experience")
        for w in profile.work_history:
            period = _join([w.get("start"), w.get("end")], " – ")
            head = _join([w.get("title"), w.get("company"), period])
            if head:
                lines.append(f"\n### {head}")
            if w.get("description"):
                lines.append(str(w["description"]))

    if profile.education:
        lines.append("\n## Education")
        for e in profile.education:
            lines.append(f"- {_join([e.get('degree'), e.get('institution'), e.get('year')])}")

    if profile.certifications:
        lines.append("\n## Certifications")
        for c in profile.certifications:
            lines.append(f"- {_join([c.get('name'), c.get('issuer'), c.get('year')])}")

    return "\n".join(lines).strip() + "\n"
