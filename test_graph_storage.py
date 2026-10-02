# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Round-trip, malformed-file, interrupted-save and actual Tk integration tests."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dijkstra_routing_demo import (
    GRAPH_FORMAT, MAX_GRAPH_BYTES, MAX_GRAPH_COST, MAX_GRAPH_ROUTERS,
    Link, Network, Router, RoutingDemo, RoutingEngine, graph_from_data,
    graph_to_data, load_graph_file, make_default_network, save_graph_file,
    tk, trace_packet,
)


class GraphStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'netværk.graph.json'
        self.network = make_default_network()

    def write_json(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')
        return self.path

    def test_round_trip_keeps_nodes_positions_links_costs_and_disabled_state(self):
        self.network.add_router(Router('G', '10.0.0.7', .321, .789), 'F', 3)
        self.network.move_router('A', .81, .12)
        self.network.update_link('D', 'E', 8, False)
        save_graph_file(self.network, self.path)
        loaded = load_graph_file(self.path)
        self.assertEqual(graph_to_data(loaded), graph_to_data(self.network))
        self.assertFalse(loaded.links[('D', 'E')].enabled)
        self.assertIsNot(loaded, self.network)
        self.assertEqual(loaded.revision, 1)

    def test_report_state_is_not_saved_or_restored(self):
        engine = RoutingEngine(self.network)
        engine.calculate_all()
        self.assertEqual(set(graph_to_data(self.network)), {'format', 'version', 'routers', 'links'})
        save_graph_file(self.network, self.path)
        restored = RoutingEngine(load_graph_file(self.path))
        self.assertEqual(restored.spf_runs, 0)
        self.assertEqual(restored.results, {})
        self.assertTrue(all(restored.table_status(name) == 'local only' for name in restored.tables))
        self.assertTrue(all(list(table) == [name] for name, table in restored.tables.items()))

    def test_rebuilt_loaded_graph_routes_to_added_node(self):
        self.network.add_router(Router('G', '10.0.0.7', .5, .8), 'F', 3)
        save_graph_file(self.network, self.path)
        engine = RoutingEngine(load_graph_file(self.path))
        engine.calculate_all()
        packet, _ = trace_packet(engine, 'A', '10.0.0.7')
        self.assertEqual(packet.path, list('ACBDEFG'))
        self.assertEqual(packet.total_cost, 13)
        self.assertEqual(packet.outcome, 'deliver')

    def test_one_router_and_zero_links(self):
        network = Network([Router('Solo', '192.0.2.1', .5, .5)], [])
        save_graph_file(network, self.path)
        restored = load_graph_file(self.path)
        self.assertEqual(restored.adjacency(), {'Solo': {}})
        engine = RoutingEngine(restored)
        engine.calculate_all()
        packet, _ = trace_packet(engine, 'Solo', '192.0.2.1')
        self.assertEqual(packet.outcome, 'deliver')

    def test_export_v11_preserves_positions_ignores_untrusted_tables(self):
        self.network.add_router(Router('G', '10.0.0.7', .31, .92), 'F', 3)
        engine = RoutingEngine(self.network)
        engine.calculate_all()
        data = engine.export_data()
        data['tables'] = {'invalid': 'not imported'}
        loaded = load_graph_file(self.write_json(data))
        self.assertEqual(graph_to_data(loaded), graph_to_data(self.network))
        self.assertEqual(RoutingEngine(loaded).spf_runs, 0)

    def test_export_v10_without_positions_uses_valid_deterministic_layout(self):
        data = RoutingEngine(self.network).export_data()
        del data['positions']
        first = graph_from_data(data)
        second = graph_from_data(data)
        self.assertEqual(graph_to_data(first), graph_to_data(second))
        self.assertEqual(first.adjacency(), self.network.adjacency())
        for r in first.routers.values():
            self.assertTrue(0 <= r.x <= 1 and 0 <= r.y <= 1)

    def test_invalid_top_level_formats(self):
        original = graph_to_data(self.network)
        cases = [None, [], 'graph', {}, {'routers': [], 'links': []}]
        for version in (True, False, '1', 1.0, None, 2, -1):
            cases.append({**original, 'version': version})
        cases += [{**original, 'format': 'other'}, {**original, 'routers': []},
                  {**original, 'routers': {}}, {**original, 'links': {}},
                  {k: v for k, v in original.items() if k != 'links'}]
        for data in cases:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                graph_from_data(data)

    def test_invalid_router_fields_are_rejected(self):
        for field, values in {
            'name': [None, [], 4, '', 'A-B', '../node'],
            'address': [None, 167772161, True, [], 'bad', '::1', '10.0.0.1/32', '0.0.0.0', '224.1.2.3'],
            'x': [None, True, [], '0.5', -1, 1.001, math.inf, math.nan, 10**500],
            'y': [None, -1, math.inf],
        }.items():
            for value in values:
                data = graph_to_data(self.network)
                data['routers'][0][field] = value
                with self.subTest(field=field, value=str(value)[:30]), self.assertRaises(ValueError):
                    graph_from_data(data)
        for entry in (None, [], {'name': 'X'}):
            data = graph_to_data(self.network)
            data['routers'][0] = entry
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                graph_from_data(data)

    def test_duplicate_names_and_addresses_rejected(self):
        for field in ('name', 'address'):
            data = graph_to_data(self.network)
            data['routers'][1][field] = data['routers'][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                graph_from_data(data)

    def test_invalid_links_are_rejected(self):
        for field, values in {'a': [None, [], 'Z', 'B'], 'b': ['A'],
                              'cost': [True, 0, -1, 2.5, '2', MAX_GRAPH_COST + 1],
                              'enabled': [0, 1, 'false', 'true', None]}.items():
            for value in values:
                data = graph_to_data(self.network)
                data['links'][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    graph_from_data(data)
        data = graph_to_data(self.network)
        first = data['links'][0]
        data['links'].append({**first, 'a': first['b'], 'b': first['a']})
        with self.assertRaises(ValueError):
            graph_from_data(data)

    def test_missing_link_fields_and_invalid_entries_rejected(self):
        for row in (None, [], {}, {'a': 'A', 'b': 'F', 'cost': 1}):
            data = graph_to_data(self.network)
            data['links'][0] = row
            with self.subTest(row=row), self.assertRaises(ValueError):
                graph_from_data(data)

    def test_partial_or_invalid_legacy_positions_are_not_silently_repaired(self):
        data = RoutingEngine(self.network).export_data()
        for positions in (None, [], {}, {'A': {'x': 0, 'y': 0}}):
            with self.subTest(positions=positions), self.assertRaises(ValueError):
                graph_from_data({**data, 'positions': positions})
        data['positions']['A'] = 'not a position'
        with self.assertRaises(ValueError):
            graph_from_data(data)

    def test_corrupt_non_json_duplicate_keys_and_nonfinite_numbers_rejected(self):
        for text in ('', '{', '[]', '__import__("os")', '{"format":"x","format":"y"}',
                     '{"x": NaN}', '{"x": Infinity}', '[' * 1500 + '0' + ']' * 1500):
            self.path.write_text(text, encoding='utf-8')
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                load_graph_file(self.path)
        self.path.write_bytes(b'\xff\xfe\x00')
        with self.assertRaises(ValueError):
            load_graph_file(self.path)

    def test_utf8_bom_is_accepted(self):
        self.path.write_text(json.dumps(graph_to_data(self.network)), encoding='utf-8-sig')
        self.assertEqual(graph_to_data(load_graph_file(self.path)), graph_to_data(self.network))

    def test_size_and_router_count_limits(self):
        self.path.write_bytes(b' ' * (MAX_GRAPH_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'too large'):
            load_graph_file(self.path)
        data = graph_to_data(self.network)
        data['routers'] *= MAX_GRAPH_ROUTERS
        with self.assertRaises(ValueError):
            graph_from_data(data)

    def test_failed_replace_preserves_existing_file_and_cleans_temp(self):
        self.path.write_text('KEEP THIS FILE', encoding='utf-8')
        with patch('dijkstra_routing_demo.os.replace', side_effect=PermissionError('write denied')):
            with self.assertRaises(OSError):
                save_graph_file(self.network, self.path)
        self.assertEqual(self.path.read_text(), 'KEEP THIS FILE')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_flush_preserves_existing_file_and_cleans_temp(self):
        self.path.write_text('KEEP THIS FILE', encoding='utf-8')
        with patch('dijkstra_routing_demo.os.fsync', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                save_graph_file(self.network, self.path)
        self.assertEqual(self.path.read_text(), 'KEEP THIS FILE')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_successful_repeated_save_replaces_destination(self):
        save_graph_file(self.network, self.path)
        self.network.move_router('A', .23, .45)
        save_graph_file(self.network, self.path)
        self.assertEqual(graph_to_data(load_graph_file(self.path)), graph_to_data(self.network))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_save_validation_failure_leaves_existing_file_unchanged(self):
        self.path.write_text('KEEP THIS FILE', encoding='utf-8')
        self.network.links[('A', 'B')].enabled = 'false'
        with self.assertRaises(ValueError):
            save_graph_file(self.network, self.path)
        self.assertEqual(self.path.read_text(), 'KEEP THIS FILE')

    def test_missing_path_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            load_graph_file(self.path)
        with self.assertRaises(OSError):
            save_graph_file(self.network, self.path.parent / 'missing' / 'graph.json')

    def test_randomized_round_trips_preserve_paths_after_recalculation(self):
        for seed in range(10):
            rng = random.Random(seed)
            network = make_default_network()
            for _ in range(4):
                node = network.suggest_router()
                network.add_router(node, rng.choice(list(network.routers)), rng.randint(1, 9))
            for r in list(network.routers.values()):
                network.move_router(r.name, rng.random(), rng.random())
            for link in list(network.links.values()):
                network.update_link(link.a, link.b, rng.randint(1, 25), rng.random() > .2)
            save_graph_file(network, self.path)
            original, restored = RoutingEngine(network), RoutingEngine(load_graph_file(self.path))
            original.calculate_all()
            restored.calculate_all()
            self.assertEqual(graph_to_data(original.network), graph_to_data(restored.network))
            self.assertEqual(original.tables, restored.tables)
            for source in network.routers:
                for target in network.routers.values():
                    p, _ = trace_packet(original, source, target.address, ttl=64)
                    q, _ = trace_packet(restored, source, target.address, ttl=64)
                    self.assertEqual((p.path, p.total_cost, p.outcome), (q.path, q.total_cost, q.outcome))


@unittest.skipUnless(tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a graphical display for Tk checks.')
class GraphStorageGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'example.graph.json'
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = RoutingDemo(self.root)
        self.root.update()
        self.error_patch = patch('dijkstra_routing_demo.messagebox.showerror')
        self.showerror = self.error_patch.start()

    def tearDown(self):
        self.error_patch.stop()
        try:
            if self.root.winfo_exists():
                if self.app.editor_window is not None:
                    self.app.editor_window.cancel_form()
                with patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=False):
                    self.app.close()
        except tk.TclError:
            pass
        self.directory.cleanup()
        self.assertEqual(self.errors, [])

    def add_g(self):
        dialog = self.app.add_router_dialog()
        dialog.form_values['neighbor'].set('F')
        dialog.form_values['cost'].set('3')
        dialog.submit_form()
        self.root.update()

    def save(self, path=None, save_as=False):
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename', return_value=str(path or self.path)):
            return self.app.save_graph(save_as=save_as)

    def load(self, path=None, answer=False):
        with patch('dijkstra_routing_demo.filedialog.askopenfilename', return_value=str(path or self.path)), \
             patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=answer):
            return self.app.load_graph()

    def test_save_load_restores_full_graph_and_resets_tables(self):
        self.add_g()
        self.app.network.move_router('G', .27, .64)
        self.app.network.update_link('A', 'B', 9, False)
        self.app._topology_changed('Test custom graph')
        wanted = graph_to_data(self.app.network)
        self.assertTrue(self.save())
        self.app.reset_network()
        self.assertNotIn('G', self.app.network.routers)
        self.assertTrue(self.load())
        self.root.update()
        self.assertEqual(graph_to_data(self.app.network), wanted)
        self.assertFalse(self.app.has_unsaved_graph())
        self.assertEqual(self.app.graph_file, self.path)
        self.assertEqual(self.app.engine.spf_runs, 0)
        self.assertIn('0/7', self.app.status_text.get())
        for selector in self.app.router_selectors:
            self.assertIn('G', selector['values'])
        self.app.build_all()
        packet, _ = trace_packet(self.app.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.total_cost, 13)
        self.assertEqual(packet.outcome, 'deliver')
        self.showerror.assert_not_called()

    def test_file_without_default_router_names_or_links_is_usable(self):
        network = Network([Router('Solo', '192.0.2.1', .5, .5)], [])
        save_graph_file(network, self.path)
        self.assertTrue(self.load())
        self.root.update()
        self.assertEqual(self.app.spf_root.get(), 'Solo')
        self.assertEqual(self.app.packet_target.get(), 'Solo')
        self.assertEqual(self.app.destination_ip.get(), '192.0.2.1')
        self.assertEqual(self.app.link_name.get(), '')
        self.assertIn('disabled', self.app.apply_link_button.state())
        self.app.apply_link()
        self.app.select_link()
        self.app.build_all()
        self.app.new_packet()
        self.app._packet_hop()
        self.assertEqual(self.app.packet.outcome, 'deliver')
        self.app.reset_network()
        self.assertEqual(len(self.app.network.routers), 6)
        self.assertNotIn('disabled', self.app.apply_link_button.state())

    def test_invalid_load_keeps_graph_tables_file_and_unsaved_changes(self):
        self.add_g()
        self.app.build_all()
        before, engine = self.app.engine.export_data(), self.app.engine
        self.path.write_text('{bad json', encoding='utf-8')
        self.assertFalse(self.load())
        self.assertEqual(self.app.engine.export_data(), before)
        self.assertIs(self.app.engine, engine)
        self.assertIsNone(self.app.graph_file)
        self.assertTrue(self.app.has_unsaved_graph())
        self.showerror.assert_called_once()

    def test_cancel_file_dialogs_preserves_current_network(self):
        self.add_g()
        before = self.app.engine.export_data()
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.app.save_graph())
        with patch('dijkstra_routing_demo.filedialog.askopenfilename', return_value=''):
            self.assertFalse(self.app.load_graph())
        self.assertEqual(self.app.engine.export_data(), before)
        self.assertTrue(self.app.has_unsaved_graph())

    def test_cancel_unsaved_prompt_aborts_loading(self):
        save_graph_file(make_default_network(), self.path)
        self.add_g()
        self.assertFalse(self.load(answer=None))
        self.assertIn('G', self.app.network.routers)
        self.assertTrue(self.app.has_unsaved_graph())

    def test_save_failure_aborts_load_and_preserves_dirty_graph(self):
        save_graph_file(make_default_network(), self.path)
        self.add_g()
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename', return_value=str(self.path)), \
             patch('dijkstra_routing_demo.os.replace', side_effect=PermissionError('test')):
            self.assertFalse(self.load(answer=True))
        self.assertIn('G', self.app.network.routers)
        self.assertTrue(self.app.has_unsaved_graph())
        self.assertEqual(len(load_graph_file(self.path).routers), 6)
        self.showerror.assert_called_once()

    def test_cancel_save_before_loading_also_cancels_load(self):
        save_graph_file(make_default_network(), self.path)
        self.add_g()
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.load(answer=True))
        self.assertIn('G', self.app.network.routers)

    def test_save_then_load_same_file_keeps_memory_and_disk_consistent(self):
        self.assertTrue(self.save())
        self.add_g()
        self.assertTrue(self.load(answer=True))
        self.assertIn('G', self.app.network.routers)
        self.assertEqual(graph_to_data(self.app.network), graph_to_data(load_graph_file(self.path)))
        self.assertFalse(self.app.has_unsaved_graph())

    def test_unsaved_move_but_not_spf_or_packet_marks_dirty(self):
        self.assertFalse(self.app.has_unsaved_graph())
        self.app.build_all()
        self.app.new_packet()
        self.assertFalse(self.app.has_unsaved_graph())
        self.app.drag_router = 'A'
        self.app.drag_offset = (0, 0)
        self.app._drag_router(SimpleNamespace(x=250, y=120))
        self.app._end_drag()
        self.assertTrue(self.app.has_unsaved_graph())
        self.assertTrue(self.root.title().endswith(' *'))
        self.assertTrue(self.save())
        self.assertFalse(self.root.title().endswith(' *'))
        self.app.build_all()
        self.assertFalse(self.app.has_unsaved_graph())

    def test_save_as_writes_another_file_and_changes_current_path(self):
        self.assertTrue(self.save())
        original = self.path.read_bytes()
        self.add_g()
        another = self.path.with_name('another.graph.json')
        self.assertTrue(self.save(another, save_as=True))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.app.graph_file, another)
        self.assertIn('G', load_graph_file(another).routers)

    def test_load_clears_pending_animation_jobs(self):
        save_graph_file(make_default_network(), self.path)
        self.app.animate_all()
        self.assertTrue(self.load())
        self.assertIsNone(self.app.iterator)
        self.assertIsNone(self.app.spf_job)
        self.assertEqual(list(self.app.spf_queue), [])
        self.app.build_all()
        self.app.new_packet()
        self.app._packet_hop()
        self.assertIsNotNone(self.app.frame_job)
        self.assertTrue(self.load())
        self.root.update()
        self.assertIsNone(self.app.packet)
        self.assertIsNone(self.app.packet_job)
        self.assertIsNone(self.app.frame_job)
        self.assertIsNone(self.app.highlight_prefix)
        self.assertIsNone(self.app.lookup_router)
        self.assertIsNone(self.app.last_decision)
        self.assertEqual(len(self.app.trace_tree.get_children()), 0)

    def test_reset_and_close_offer_save_discard_cancel(self):
        self.add_g()
        with patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=None):
            self.app.reset_network()
            self.app.close()
        self.assertIn('G', self.app.network.routers)
        self.assertTrue(self.root.winfo_exists())
        with patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=True), \
             patch('dijkstra_routing_demo.filedialog.asksaveasfilename', return_value=str(self.path)):
            self.app.reset_network()
        self.assertEqual(len(self.app.network.routers), 6)
        self.assertIn('G', load_graph_file(self.path).routers)
        self.assertIsNone(self.app.graph_file)

    def test_file_shortcuts_do_not_bypass_active_router_dialog(self):
        dialog = self.app.add_router_dialog()
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename') as save, \
             patch('dijkstra_routing_demo.filedialog.askopenfilename') as load:
            self.assertFalse(self.app.save_graph())
            self.assertFalse(self.app.load_graph())
            save.assert_not_called()
            load.assert_not_called()
        dialog.cancel_form()


if __name__ == '__main__':
    unittest.main()
