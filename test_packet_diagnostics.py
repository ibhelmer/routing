# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for non-TTL drops, explicit preflight and live TTL display.

Run headless: python -m unittest -v
Opt into actual Tk widgets with RUN_GUI_TESTS=1 and a graphical display.
Native confirmation responses are mocked; no dialog is answered by automation.
"""
import ipaddress
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dijkstra_routing_demo as demo


class PacketDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = demo.RoutingEngine(demo.make_default_network())

    def test_startup_drop_is_not_ttl_expiry(self):
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual((packet.ttl, trace[-1].reason_code), (16, 'NO_SPF'))
        self.assertIn('not a TTL expiry', trace[-1].message)

    def test_only_a_calculated_drops_at_c_with_ttl_remaining(self):
        self.engine.calculate('A')
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, ['A', 'C'])
        self.assertEqual((packet.ttl, trace[-1].reason_code), (15, 'NO_SPF'))
        self.assertIn('C has not completed SPF', trace[-1].message)

    def test_all_default_pairs_deliver_without_running_spf_in_forwarding(self):
        self.engine.calculate_all()
        with patch('dijkstra_routing_demo.dijkstra_steps', side_effect=AssertionError('SPF while forwarding')):
            for source in self.engine.tables:
                for router in self.engine.network.routers.values():
                    packet, trace = demo.trace_packet(self.engine, source, router.address, ttl=64)
                    self.assertEqual(packet.outcome, 'deliver')
                    self.assertEqual(trace[-1].reason_code, '')
        self.assertEqual(self.engine.spf_runs, 6)

    def test_old_table_without_new_destination_has_its_own_reason(self):
        self.engine.calculate_all()
        self.engine.add_router(demo.Router('G', '10.0.0.7', .5, .6), 'F', 3)
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.7')
        self.assertEqual((packet.ttl, trace[-1].reason_code), (16, 'STALE_NO_ROUTE'))

    def test_unknown_destination_is_no_route_not_no_spf(self):
        self.engine.calculate_all()
        packet, trace = demo.trace_packet(self.engine, 'A', '10.99.0.1')
        self.assertEqual((packet.ttl, trace[-1].reason_code), (16, 'NO_ROUTE'))
        self.assertIn('table is current', trace[-1].message)

    def test_isolated_destination_cannot_be_fixed_by_ttl(self):
        self.engine.add_router(demo.Router('G', '10.0.0.7', .5, .6))
        self.engine.calculate_all()
        for ttl in (16, 64, 255):
            packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.7', ttl)
            self.assertEqual((packet.ttl, trace[-1].reason_code), (ttl, 'NO_ROUTE'))

    def test_down_link_preserves_failed_next_hop_and_remaining_ttl(self):
        self.engine.calculate_all()
        self.engine.network.update_link('D', 'E', 1, False)
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, list('ACBD'))
        self.assertEqual((trace[-1].reason_code, trace[-1].next_hop, packet.ttl), ('LINK_DOWN', 'E', 13))
        self.engine.calculate_all()
        packet, _ = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual((packet.outcome, packet.path, packet.total_cost), ('deliver', list('ACEF'), 11))

    def test_invalid_next_hop_is_distinct_from_a_disabled_link(self):
        self.engine.calculate_all()
        prefix = ipaddress.IPv4Network('10.0.0.6/32')
        self.engine.tables['A']['F'] = demo.Route('F', prefix, 'Z', 10)
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual((trace[-1].reason_code, trace[-1].next_hop, packet.ttl), ('INVALID_NEXT_HOP', 'Z', 16))

    def test_ttl_expires_only_on_forwarding_and_initial_value_is_preserved(self):
        self.engine.calculate_all()
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6', 3)
        self.assertEqual((packet.initial_ttl, packet.ttl), (3, 0))
        self.assertEqual(trace[-1].reason_code, 'TTL_EXPIRED')
        self.assertEqual((trace[-1].ttl_before, trace[-1].ttl_after), (1, 0))
        self.assertEqual(trace[-1].next_hop, 'D')
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6', 6)
        self.assertEqual((packet.ttl, packet.outcome), (1, 'deliver'))

    def test_stale_flag_alone_does_not_drop_a_valid_packet(self):
        self.engine.calculate_all()
        self.engine.network.update_link('A', 'B', 7, False)  # Not used by A -> F.
        packet, trace = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual((packet.path, packet.outcome, packet.ttl), (list('ACBDEF'), 'deliver', 11))
        self.assertTrue(all(not decision.reason_code for decision in trace))


@unittest.skipUnless(demo.tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a graphical display for Tk checks.')
class PacketDiagnosticsGuiTests(unittest.TestCase):
    def setUp(self):
        self.ask_patch = patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=False)
        self.ask = self.ask_patch.start()
        self.root = demo.tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = demo.RoutingDemo(self.root)
        self.root.update()

    def tearDown(self):
        if self.app.about_window is not None:
            self.app.close_about()
        if self.app.editor_window is not None:
            self.app.editor_window.cancel_form()
        self.ask.return_value = False
        self.app.close()
        self.ask_patch.stop()
        self.assertEqual(self.errors, [])

    def run_packet(self):
        self.app.speed.set(.12)
        self.app.toggle_packet()
        deadline = time.monotonic() + 4
        while not self.app.packet.done and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)
        self.assertTrue(self.app.packet.done)
        self.root.update()

    def test_yes_builds_all_tables_before_injection_then_delivers(self):
        self.ask.return_value = True
        self.assertTrue(self.app.new_packet())
        self.ask.assert_called_once()
        self.assertEqual(self.app.engine.spf_runs, 6)
        with patch('dijkstra_routing_demo.dijkstra_steps', side_effect=AssertionError('SPF while forwarding')):
            self.run_packet()
        self.assertEqual(self.app.packet.outcome, 'deliver')
        self.assertIn('TTL now 11 (initial 16)', self.app.packet_state.get())
        self.assertFalse(self.app.has_unsaved_graph())

    def test_no_allows_a_deliberate_missing_table_drop_and_explains_it(self):
        self.app.engine.calculate('A')
        self.assertTrue(self.app.new_packet())
        self.assertEqual(self.app.engine.spf_runs, 1)
        self.run_packet()
        self.assertEqual(self.app.last_decision.reason_code, 'NO_SPF')
        self.assertIn('TTL now 15 (initial 16)', self.app.packet_state.get())
        self.assertEqual(self.app.trace_tree.item('2', 'values')[3], 'DROP: NO_SPF')
        self.assertIn('C has not completed SPF', self.app.packet_note.get())

    def test_cancel_keeps_unfinished_spf_and_existing_tables(self):
        self.app.animate_all()
        iterator, queue = self.app.iterator, list(self.app.spf_queue)
        before = self.app.engine.export_data()
        self.ask.return_value = None
        self.assertFalse(self.app.new_packet())
        self.assertIsNone(self.app.packet)
        self.assertIs(self.app.iterator, iterator)
        self.assertEqual(list(self.app.spf_queue), queue)
        self.assertEqual(self.app.engine.export_data(), before)
        self.assertFalse(self.app.spf_auto)
        self.assertIsNone(self.app.spf_job)

    def test_cancel_keeps_previous_packet_paused(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.step_packet()
        packet = self.app.packet
        # Headless topology mutation to emulate externally retained installed tables.
        self.app.network.update_link('A', 'B', 7, False)
        before = (packet.ttl, list(packet.path), self.app.engine.spf_runs)
        self.ask.return_value = None
        self.assertFalse(self.app.new_packet())
        self.assertIs(self.app.packet, packet)
        self.assertEqual((packet.ttl, list(packet.path), self.app.engine.spf_runs), before)
        self.assertFalse(self.app.packet_auto)
        self.assertIsNone(self.app.frame_job)

    def test_current_tables_do_not_prompt_or_trigger_spf(self):
        self.app.build_all()
        self.assertTrue(self.app.new_packet())
        self.ask.assert_not_called()
        self.assertEqual(self.app.engine.spf_runs, 6)

    def test_local_loopback_without_spf_does_not_prompt(self):
        self.app.destination_ip.set('10.0.0.1')
        self.app.ttl_value.set('1')
        self.assertTrue(self.app.new_packet())
        self.app._packet_hop()
        self.assertEqual(self.app.packet.outcome, 'deliver')
        self.assertIn('TTL now 1 (initial 1)', self.app.packet_state.get())
        self.ask.assert_not_called()

    def test_stale_tables_no_keeps_failed_link_experiment(self):
        self.app.build_all()
        self.app.toggle_link(('D', 'E'))
        self.assertTrue(self.app.new_packet())
        self.assertEqual(self.app.engine.spf_runs, 6)
        self.run_packet()
        self.assertEqual((self.app.last_decision.reason_code, self.app.packet.ttl), ('LINK_DOWN', 13))
        self.assertIn('TTL now 13', self.app.packet_state.get())

    def test_stale_tables_yes_rebuilds_but_does_not_enable_failed_link(self):
        self.app.build_all()
        self.app.toggle_link(('D', 'E'))
        self.ask.return_value = True
        self.assertTrue(self.app.new_packet())
        self.assertEqual(self.app.engine.spf_runs, 12)
        self.assertFalse(self.app.network.links[('D', 'E')].enabled)
        self.run_packet()
        self.assertEqual((self.app.packet.path, self.app.packet.total_cost), (list('ACEF'), 11))

    def test_changed_initial_ttl_does_not_misrepresent_existing_packet(self):
        self.app.build_all()
        self.app.ttl_value.set('3')
        self.app.new_packet()
        self.app.ttl_value.set('64')
        self.run_packet()
        self.assertEqual(self.app.last_decision.reason_code, 'TTL_EXPIRED')
        self.assertIn('TTL now 0 (initial 3)', self.app.packet_state.get())
        self.assertEqual(self.app.ttl_value.get(), '64')
        self.app.new_packet()
        self.assertEqual(self.app.packet.ttl, 64)
        self.assertIn('TTL now 64 (initial 64)', self.app.packet_state.get())

    def test_newly_loaded_graph_offers_build_before_sending(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'test.graph.json'
            demo.save_graph_file(self.app.network, filename)
            with patch('dijkstra_routing_demo.filedialog.askopenfilename', return_value=str(filename)):
                self.assertTrue(self.app.load_graph())
        self.ask.return_value = True
        self.assertTrue(self.app.new_packet())
        self.assertEqual(self.app.engine.spf_runs, 6)
        self.run_packet()
        self.assertEqual(self.app.packet.outcome, 'deliver')

    def test_historical_trace_row_shows_its_original_decision(self):
        self.app.build_all()
        self.app.new_packet()
        self.run_packet()
        self.app.trace_tree.selection_set('1')
        self.root.update()
        self.assertIn('TTL 16 -> 15', self.app.packet_note.get())
        self.assertIn('TTL now 11', self.app.packet_state.get())
        self.app.stop_packet()
        self.root.update()
        self.assertEqual(self.app.trace_decisions, {})
        self.assertIn('No packet', self.app.packet_state.get())

    def test_about_and_editor_dialogs_block_new_packets_and_confirmation(self):
        self.app.show_about()
        self.assertFalse(self.app.new_packet())
        self.app.close_about()
        self.app.add_router_dialog()
        self.assertFalse(self.app.new_packet())
        self.ask.assert_not_called()

    def test_compact_drop_keeps_ttl_input_nodes_and_selected_reason_visible(self):
        self.app.engine.calculate('A')
        self.app.new_packet()
        self.run_packet()
        self.root.geometry('1180x740')
        self.root.update()
        spinbox = self.app.initial_ttl_spinbox
        self.assertLessEqual(spinbox.winfo_rootx() + spinbox.winfo_width(),
                             self.app.canvas.winfo_rootx() + self.app.canvas.winfo_width())
        self.assertTrue(self.app.trace_tree.bbox('2'))
        self.assertEqual(self.app.trace_tree.item('2', 'values')[3], 'DROP: NO_SPF')
        for x, y in self.app._positions().values():
            self.assertLessEqual(y + 26, self.app.canvas.winfo_height())

    def test_yes_does_not_fabricate_a_route_to_an_isolated_router(self):
        dialog = self.app.add_router_dialog()
        dialog.submit_form()  # G, no connection.
        self.ask.return_value = True
        self.app.new_packet()
        self.run_packet()
        self.assertEqual(self.app.last_decision.reason_code, 'NO_ROUTE')
        self.assertEqual(self.app.packet.ttl, 16)
        self.assertEqual(len(self.app.network.links), 9)


if __name__ == '__main__':
    unittest.main()
