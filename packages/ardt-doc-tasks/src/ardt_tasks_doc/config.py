"""The ``tasks:`` config section, ``doc:`` subsection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ardt_core.config import ArdtConfig

DOC_OUTPUT = "build/doc"
"""Fixed output convention: html at ``build/doc/html``, doxygen XML at
``build/doc/doxygen/xml``. The preset finds the XML by this path (relative to
the project root, which is the working directory of every ardt-driven sphinx
run) and pipelines export the html blindly — same idea as the JUnit glob."""


class DocConfig(BaseModel):
    """``tasks.doc:`` — everything the doc task needs from the repo."""

    model_config = ConfigDict(extra="forbid")

    source_dir: str = "doc"
    """The sphinx project directory (holds ``conf.py``), relative to the root."""

    doxygen: bool | Literal["auto"] = "auto"
    """Run Doxygen before sphinx so breathe has XML to read. ``auto`` switches
    it on when the repo contains C/C++ sources."""

    doxygen_input: list[str] = Field(default_factory=list)
    """Directories Doxygen scans, relative to the root; empty means the whole
    repo (minus build/install/log/test trees)."""

    strict: bool = True
    """Warnings are errors (``sphinx -W --keep-going``) — the doc equivalent of
    a red test."""


class TasksSection(BaseModel):
    """``tasks:`` — the section this plugin shares with the other task plugins."""

    model_config = ConfigDict(extra="allow")

    doc: DocConfig = Field(default_factory=DocConfig)


def doc_config(cfg: ArdtConfig) -> DocConfig:
    """Extract ``tasks.doc:`` from the repo config, with defaults."""
    return cfg.section_as("tasks", TasksSection).doc
