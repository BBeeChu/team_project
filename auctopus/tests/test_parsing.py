import unittest

from auctopus.parsing import (best_seed, extract_files, is_junk_reply, is_proposal, pi_selected, parse_keep,
                               safe_relpath, selected_proposer, strip_file_blocks)
from auctopus.stages.chain import decision_line, figure_verdict, lab_decision, review_verdict
from auctopus.stages.lab import safety_verdict


class KeepLine(unittest.TestCase):
    names = ["proposer-1.md", "proposer-2.md", "proposer-3.md"]

    def test_last_keep_line_wins_and_order_is_kept(self):
        reply = "KEEP: proposer-1.md\nthinking...\n**KEEP:** proposer-3.md, proposer-1.md"
        self.assertEqual(parse_keep(reply, self.names), ["proposer-1.md", "proposer-3.md"])

    def test_unknown_names_are_ignored_and_empty_fails_open(self):
        self.assertIsNone(parse_keep("KEEP: proposer-9.md", self.names))
        self.assertIsNone(parse_keep("no line at all", self.names))


class Verdict(unittest.TestCase):
    def test_the_selection_line_decides(self):
        self.assertTrue(pi_selected("SELECTION: proposer-3\n\nNo winner was obvious, but proposer-3 is the strongest."))
        self.assertFalse(pi_selected("**SELECTION: none**\n\nBEST SEED: proposer-2"))
        self.assertFalse(pi_selected("SELECTION: proposer-1\n...\nSELECTION: none"))
        self.assertEqual(selected_proposer("SELECTION: **proposer 4**\n\nSelect proposer-2 later."), "proposer-4")
        self.assertIsNone(selected_proposer("SELECTION: none"))

    def test_no_winner_detected_only_in_first_1200_chars(self):
        self.assertFalse(pi_selected("# Verdict: no winner\n\nBEST SEED: proposer-2"))
        self.assertFalse(pi_selected("We would reject all proposals."))
        self.assertTrue(pi_selected("**Select proposer-2: X.**\n" + "x" * 1300 + " no winner"))

    def test_best_seed_last_hit_and_none(self):
        self.assertEqual(best_seed("BEST SEED: proposer-1\n...\nBEST SEED: **proposer 4**"), "proposer-4")
        self.assertIsNone(best_seed("BEST SEED: none"))
        self.assertIsNone(best_seed("nothing"))


class ProposerReplies(unittest.TestCase):
    def test_junk_filter_keeps_refusals(self):
        self.assertTrue(is_junk_reply("Something went wrong."))
        refusal = "I cannot find a sufficiently novel idea under these constraints. " * 20
        self.assertFalse(is_junk_reply(refusal))
        self.assertFalse(is_proposal(refusal, 600))
        self.assertTrue(is_proposal("word " * 600, 600))


class ChainVerdicts(unittest.TestCase):
    def test_review_verdict_exact_and_fallback(self):
        self.assertEqual(review_verdict("...\nVERDICT: ACCEPT\n...\nVERDICT: **REVISE**"), "REVISE")
        self.assertEqual(review_verdict("Verdict - pass. Fine."), "ACCEPT")
        self.assertEqual(review_verdict("No verdict line here"), "REVISE")

    def test_figure_and_lab_lines(self):
        self.assertEqual(figure_verdict("FIGURE: REVISE\n1. x\nFIGURES: ACCEPT"), "ACCEPT")
        self.assertEqual(figure_verdict("nothing"), "UNKNOWN")
        self.assertEqual(lab_decision("LAB-DECISION: **GO**"), "GO")
        self.assertEqual(lab_decision("LAB-DECISION: NO-GO"), "NO-GO")
        self.assertEqual(lab_decision("missing"), "NO-GO")
        self.assertEqual(decision_line("EXPORT-RULING: REVISE AND SUPPLEMENT", "EXPORT-RULING"),
                         "REVISE AND SUPPLEMENT")

    def test_safety_line_fails_closed(self):
        self.assertEqual(safety_verdict("1. Within limits.\n\nSAFETY: **APPROVE**"), "APPROVE")
        self.assertEqual(safety_verdict("SAFETY: APPROVE\n...\nSAFETY: REJECT"), "REJECT")
        self.assertEqual(safety_verdict("Looks fine to me."), "REJECT")


class FileBlocks(unittest.TestCase):
    def test_extract_and_reject_unsafe_paths(self):
        reply = ("intro\n===== FILE: main.tex =====\n\\documentclass{article}\n===== END FILE =====\n"
                 "===== FILE: ../evil.sh =====\nrm -rf /\n===== END FILE =====\n"
                 "===== FILE: sections/a.tex =====\nA\n===== END FILE =====\n")
        files = extract_files(reply)
        self.assertEqual(sorted(files), ["main.tex", "sections/a.tex"])
        self.assertIn("\\documentclass", files["main.tex"])
        self.assertIsNone(safe_relpath("/etc/passwd"))
        self.assertIn("[file main.tex delivered]", strip_file_blocks(reply))


if __name__ == "__main__":
    unittest.main()
