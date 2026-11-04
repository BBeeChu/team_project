"""A multi-turn conversation kept on disk.

The PI's conversation carries state across stages: the selection verdict, proofs, positioning, manuscript, experiment
designs and the review rounds all see the earlier turns. Every turn is saved as soon as it exists, so a crash never
loses a paid reply, and a background request that was running when the pipeline stopped is resumed by its response id
instead of being sent again.
"""
from __future__ import annotations

import threading
from pathlib import Path

from .attachments import content_text, strip_attachments
from .config import Config
from .llm import LLMReply, get_client
from .llm.base import LLMCancelled
from .util import LOG, atomic_write_text, iso_now, read_json, write_json


class Conversation:
    owner: str | None = None    # the pipeline stage currently running; recorded on new conversations and turns

    def __init__(self, cfg: Config, path: Path, role_name: str, system: str | None = None):
        self.cfg = cfg
        self.path = Path(path)
        self.role_name = role_name
        data = read_json(self.path, default=None)
        if data is None:
            data = {"role": role_name, "system": system, "turns": [], "pending": None, "compactions": 0,
                    "owner": Conversation.owner}
        self.data = data

    # ------------------------------------------------------------------ access
    @property
    def turns(self) -> list[dict]:
        return self.data["turns"]

    def messages(self) -> list[dict]:
        """The history to send: attachments travel only with the latest user turn."""
        last_user = max((i for i, t in enumerate(self.turns) if t["role"] == "user"), default=-1)
        return [{"role": t["role"],
                 "content": t["content"] if (t["role"] != "user" or i == last_user) else strip_attachments(
                     t["content"])}
                for i, t in enumerate(self.turns)]

    def reply_for(self, stage: str) -> str | None:
        """The assistant reply recorded for a stage (latest), or None."""
        for t in reversed(self.turns):
            if t["role"] == "assistant" and t.get("stage") == stage:
                return t["content"]
        return None

    def _save(self) -> None:
        write_json(self.path, self.data)

    # -------------------------------------------------------------------- send
    def send(self, content: str | list[dict], stage: str, reply_file: Path | None = None,
             role_name: str | None = None, cancel: threading.Event | None = None) -> LLMReply:
        """Send one user turn (text, or text plus attachments from attachments.build_content) and record the reply.
        Idempotent per stage: if the stage's user turn is already the last turn (the previous attempt crashed before
        the reply arrived), it is not appended twice. `role_name` serves this turn with another role's model and
        effort while keeping the same history (the PI reviews at another setting inside its own conversation)."""
        role_name = role_name or self.role_name
        role = self.cfg.role(role_name)
        last = self.turns[-1] if self.turns else None
        if not (last and last["role"] == "user" and last.get("stage") == stage):
            self.turns.append({"role": "user", "content": content, "stage": stage, "at": iso_now(),
                               "owner": Conversation.owner})
            self._save()
        self._maybe_compact(stage)
        resume_id = None
        pending = self.data.get("pending")
        if pending and pending.get("stage") == stage and pending.get("response_id"):
            resume_id = pending["response_id"]
            LOG.info("%s: resuming the running request %s", stage, resume_id)

        def started(rid: str) -> None:
            self.data["pending"] = {"stage": stage, "response_id": rid, "at": iso_now()}
            self._save()

        client = get_client(self.cfg, role_name)
        try:
            reply = client.complete(self.messages(), system=self.data.get("system"), role=role, stage=stage,
                                    on_started=started, resume_id=resume_id, cancel=cancel)
        except LLMCancelled:
            self.data["pending"] = None      # a cancelled request is never resumed
            self._save()
            raise
        self.turns.append({"role": "assistant", "content": reply.text, "stage": stage, "at": iso_now(),
                           "owner": Conversation.owner, "model": reply.model, "provider": reply.provider,
                           "response_id": reply.response_id, "usage": reply.usage,
                           "elapsed_s": round(reply.elapsed_s, 1), "truncated": reply.truncated})
        self.data["pending"] = None
        self._save()
        if reply_file is not None:
            atomic_write_text(Path(reply_file), reply.text)
        return reply

    # ---------------------------------------------------------------- compaction
    def _maybe_compact(self, stage: str) -> None:
        """Keep the conversation under the configured size: summarise the older turns into one context turn and keep
        the most recent exchange verbatim, so a long investigation stays inside the model's context window."""
        budget = self.cfg.project.max_history_chars
        size = sum(len(content_text(m["content"])) for m in self.messages())    # what would actually be sent
        if budget <= 0 or size <= budget or len(self.turns) < 6:
            return
        keep = self.turns[-3:]                 # last exchange plus the new user turn
        older = self.turns[:-3]
        role = self.cfg.role(self.role_name)
        client = get_client(self.cfg, self.role_name)
        prompt = ("Summarize this research conversation so far for your own later use. Keep every decision, claim, "
                  "theorem statement, definition, number, design choice, reviewer requirement and open issue; keep "
                  "the paper's story and terminology exactly. Omit pleasantries. This summary will replace the "
                  "earlier turns.")
        LOG.info("%s: conversation is %d characters (> %d); compacting %d earlier turns", stage, size, budget,
                 len(older))
        summary = client.complete([{"role": t["role"], "content": strip_attachments(t["content"])
                                    if t["role"] == "user" else t["content"]} for t in older] +
                                  [{"role": "user", "content": prompt}],
                                  system=self.data.get("system"), role=role, stage=f"{stage}-compact").text
        archive = self.path.with_name(self.path.stem + f".before-compaction-{self.data['compactions'] + 1}.json")
        write_json(archive, {"turns": older})
        self.data["turns"] = [
            {"role": "user", "content": "Context: summary of our conversation so far.\n\n" + summary,
             "stage": "compacted", "at": iso_now()},
            {"role": "assistant", "content": "Understood. I will continue from this summary.", "stage": "compacted",
             "at": iso_now()},
        ] + keep
        self.data["compactions"] += 1
        self._save()


def one_shot(cfg: Config, role_name: str, content: str | list[dict], stage: str, out_file: Path | None = None,
             record: Path | None = None, system: str | None = None,
             cancel: threading.Event | None = None) -> LLMReply:
    """A fresh single-turn conversation (no shared history). Recorded on disk if `record` is given,
    which also makes it resumable: a finished stage is never paid for twice."""
    if record is not None:
        conv = Conversation(cfg, record, role_name, system=system)
        done = conv.reply_for(stage)
        if done is not None:
            if out_file is not None and not Path(out_file).exists():
                atomic_write_text(Path(out_file), done)
            return LLMReply(text=done, provider="cached", model="", stop_reason="cached")
        return conv.send(content, stage, reply_file=out_file, cancel=cancel)
    client = get_client(cfg, role_name)
    reply = client.complete([{"role": "user", "content": content}], system=system, role=cfg.role(role_name),
                            stage=stage, cancel=cancel)
    if out_file is not None:
        atomic_write_text(Path(out_file), reply.text)
    return reply
