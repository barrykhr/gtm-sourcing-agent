"""CLI entry point. Every command maps 1:1 to a pipeline stage — see
README.md for the full command list and ARCHITECTURE.md for why the
pipeline is shaped this way.

Every command that calls a stage is wrapped in `@_friendly_errors` so a
missing upstream checkpoint (`ValueError` from storage.require_section)
or an LLM-call failure (`RuntimeError` from llm_client.generate) prints a
one-line message and exits non-zero, instead of a raw Python traceback —
a recruiter running this from a terminal shouldn't need to read a stack
trace to learn "run intake first".
"""

import functools
import json
import logging
from pathlib import Path
from typing import Optional

import typer

from . import pipeline, storage
from .models.funnel import ForecastAssumptions
from .stages import (
    calibration as calibration_stage,
)
from .stages import (
    candidate_analysis as candidate_analysis_stage,
)
from .stages import (
    funnel as funnel_stage,
)
from .stages import (
    icp as icp_stage,
)
from .stages import (
    intake as intake_stage,
)
from .stages import (
    outreach as outreach_stage,
)
from .stages import (
    prioritization as prioritization_stage,
)
from .stages import (
    screening as screening_stage,
)
from .stages import (
    search_strategy as search_strategy_stage,
)
from .stages import (
    talent_map as talent_map_stage,
)

app = typer.Typer(help="Talyn — recruiter stays the decision-maker.")
candidate_app = typer.Typer(help="Per-candidate commands.")
funnel_app = typer.Typer(help="Funnel tracking and forecasting.")
app.add_typer(candidate_app, name="candidate")
app.add_typer(funnel_app, name="funnel")


def _friendly_errors(fn):
    """Turn a checkpoint-gating ValueError or an llm_client RuntimeError
    into a one-line stderr message + exit code 1, instead of a traceback."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, RuntimeError) as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from None

    return wrapper


@app.callback()
def main(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show llm_client.generate() stage/token logs."
    ),
):
    """Talyn — recruiter stays the decision-maker."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
@_friendly_errors
def intake(
    jd_path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="path to the JD text file"
    ),
    role_id: str = typer.Option(..., "--role-id"),
):
    """Stage 1: parse a JD file into a structured JobDescription."""
    result = intake_stage.run(role_id, jd_path.read_text())
    typer.echo(result.model_dump_json(indent=2))


@app.command()
@_friendly_errors
def calibrate(role_id: str):
    """Stage 2: generate the hiring manager calibration sheet."""
    result = calibration_stage.run(role_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
@_friendly_errors
def icp(role_id: str):
    """Stage 3: generate the Ideal Candidate Profile."""
    result = icp_stage.run(role_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command(name="talent-map")
@_friendly_errors
def talent_map_cmd(role_id: str):
    """Stage 4-5: generate target companies + title intelligence."""
    result = talent_map_stage.run(role_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command(name="search-strategy")
@_friendly_errors
def search_strategy_cmd(role_id: str):
    """Stage 6: generate search strategies against the talent map."""
    result = search_strategy_stage.run(role_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def status(role_id: str):
    """Show which role-level stages have run, and what's next."""
    for name, done in pipeline.status(role_id).items():
        typer.echo(f"  [{'x' if done else ' '}] {name}")
    nxt = pipeline.next_stage(role_id)
    typer.echo(f"next: {nxt or '(role-level pipeline complete)'}")


SHOW_SECTIONS = (
    "job_description",
    "calibration",
    "icp",
    "talent_map",
    "candidates",
    "prioritizations",
    "screening",
    "outreach",
    "funnel",
    "funnel_metrics",
)


@app.command()
def show(
    role_id: str,
    section: Optional[str] = typer.Argument(
        None, help=f"one of {', '.join(SHOW_SECTIONS)} — omit to dump the whole workspace file"
    ),
):
    """Print a role's stored workspace state (or one section of it) as JSON
    — for reviewing/editing what a stage produced without hand-opening
    workspace/<role_id>.json."""
    state = storage.load_role(role_id)
    if section is None:
        typer.echo(json.dumps(state, indent=2, default=str))
        return
    if section not in state or not state[section]:
        typer.echo(f"No '{section}' data yet for role '{role_id}'.", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(state[section], indent=2, default=str))


@candidate_app.command("add")
@_friendly_errors
def candidate_add(
    role_id: str,
    source_path: Path = typer.Option(
        ..., "--source-path", exists=True, dir_okay=False, readable=True,
        help="resume/profile text file",
    ),
    role_family: str = typer.Option(..., "--role-family", help="e.g. sales, csm, sdr, engineering"),
    source_url: str = typer.Option("", "--source-url"),
):
    """Stage 7: structure a candidate from recruiter-supplied source text."""
    result = candidate_analysis_stage.run(
        role_id, source_path.read_text(), role_family, source_url=source_url
    )
    typer.echo(result.model_dump_json(indent=2))


@candidate_app.command("list")
def candidate_list(role_id: str):
    """List candidates captured for this role, with prioritization tier
    (if set) and recruiter decision (if recorded) — a quick roster view
    without opening the workspace JSON."""
    state = storage.load_role(role_id)
    candidates = state.get("candidates") or {}
    prioritizations = state.get("prioritizations") or {}
    if not candidates:
        typer.echo(f"No candidates yet for role '{role_id}'.")
        return
    for candidate_id, c in candidates.items():
        p = prioritizations.get(candidate_id) or {}
        tier = p.get("tier", "-")
        decision = p.get("recruiter_decision") or ""
        line = f"[{tier}] {candidate_id}  {c.get('name', '')} — {c.get('current_title', '')} @ {c.get('current_company', '')}"
        if decision:
            line += f"  (recruiter: {decision})"
        typer.echo(line)


@app.command()
@_friendly_errors
def prioritize(role_id: str, candidate_id: str):
    """Stage 8: tier a candidate A/B/C/D with rationale (never a rejection)."""
    result = prioritization_stage.run(role_id, candidate_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
@_friendly_errors
def screen(role_id: str, candidate_id: str):
    """Stage 10: generate targeted screening questions."""
    result = screening_stage.run(role_id, candidate_id)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
@_friendly_errors
def outreach(role_id: str, candidate_id: str):
    """Stage 11: draft outreach (draft only — this never sends anything)."""
    result = outreach_stage.run(role_id, candidate_id)
    typer.echo(result.model_dump_json(indent=2))


@funnel_app.command("update")
@_friendly_errors
def funnel_update(role_id: str, candidate_id: str, stage: str):
    """Move a candidate to a funnel stage (e.g. CONTACTED, HM_INTERVIEW)."""
    record = funnel_stage.update(role_id, candidate_id, stage.upper())
    typer.echo(record)


@funnel_app.command("report")
def funnel_report(role_id: str):
    """Stage 12: funnel conversion metrics + biggest leakage stage."""
    result = funnel_stage.report(role_id)
    typer.echo(result.model_dump_json(indent=2))


@funnel_app.command("forecast")
@_friendly_errors
def funnel_forecast(
    hires: int,
    weeks: int,
    source: str = typer.Option("market_default", help="'historical' or 'market_default'"),
    screen_to_hm: float = 0.5,
    hm_to_final: float = 0.5,
    final_to_offer: float = 0.5,
    offer_to_accept: float = 0.8,
    contacted_to_screen: float = 0.3,
    sourced_to_contacted: float = 0.3,
):
    """Stage 13: back-calculate required sourcing volume for N hires.

    Default rates are illustrative market defaults, NOT measured history
    — pass --source historical only when the rates came from this
    recruiter's own funnel data (see funnel report)."""
    assumptions = ForecastAssumptions(
        source=source,
        screen_to_hm_interview=screen_to_hm,
        hm_interview_to_final=hm_to_final,
        final_to_offer=final_to_offer,
        offer_to_accept=offer_to_accept,
        contacted_to_screen=contacted_to_screen,
        sourced_to_contacted=sourced_to_contacted,
    )
    result = funnel_stage.forecast(hires, weeks, assumptions)
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
