# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Dynamic topology tests; opt into real Tk checks with RUN_GUI_TESTS=1."""
import ipaddress
import math
import os
import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dijkstra_routing_demo import (
    Router, RoutingDemo, RoutingEngine, dijkstra_steps, make_default_network,
    tk, trace_packet,
)


class TopologyEditorModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = RoutingEngine(make_default_network())
        self.network = self.engine.network
        self.engine.calculate_all()

    def test_new_router_has_local_route_and_old_tables_stay_installed(self):
        old = self.engine.tables['A']
        self.engine.add_router(Router('G', '10.0.0.7', .5, .5))
        self.assertIs(self.engine.tables['A'], old)
        self.assertEqual(self.engine.table_status('A'), 'STALE')
        self.assertEqual(self.engine.table_status('G'), 'local only')
        self.assertEqual(list(self.engine.tables['G']), ['G'])
        self.assertEqual(self.engine.spf_runs, 6)
        packet, _ = trace_packet(self.engine, 'G', '10.0.0.7', ttl=1)
        self.assertEqual(packet.outcome, 'deliver')

    def test_isolated_router_then_connected_and_recomputed(self):
        self.engine.add_router(Router('G', '10.0.0.7', .5, .5))
        self.engine.calculate_all()
        self.assertNotIn('G', self.engine.tables['A'])
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.outcome, 'drop')
        self.network.add_link('F', 'G', 3)
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.outcome, 'drop')  # Old table is still installed.
        self.engine.calculate_all()
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.path, list('ACBDEFG'))
        self.assertEqual(packet.total_cost, 13)
        self.assertEqual(packet.outcome, 'deliver')

    def test_router_with_first_link_is_one_revision(self):
        revision = self.network.revision
        self.engine.add_router(Router('G', '10.0.0.7', .5, .5), 'F', 3)
        self.assertEqual(self.network.revision, revision + 1)
        self.assertEqual(self.network.links[('F', 'G')].cost, 3)
        self.engine.calculate_all()
        packet, _ = trace_packet(self.engine, 'G', '10.0.0.1')
        self.assertEqual(packet.path, list('GFEDBCA'))
        self.assertEqual(packet.total_cost, 13)

    def test_new_shortcut_changes_forwarding_only_after_spf(self):
        self.network.add_link('A', 'F', 1)
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, list('ACBDEF'))
        self.engine.calculate_all()
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, ['A', 'F'])
        self.assertEqual(packet.total_cost, 1)

    def test_invalid_router_inputs_do_not_partially_modify_model(self):
        cases = [
            (Router('A', '10.0.0.7', .5, .5), None, 1),
            (Router('G', '10.0.0.1', .5, .5), None, 1),
            (Router('G', 'not-an-ip', .5, .5), None, 1),
            (Router('G', '::1', .5, .5), None, 1),
            (Router('G', '10.0.0.7/32', .5, .5), None, 1),
            (Router('G', '0.0.0.0', .5, .5), None, 1),
            (Router('G', '224.0.0.1', .5, .5), None, 1),
            (Router('G', '255.255.255.255', .5, .5), None, 1),
            (Router('G', '10.0.0.7', .5, .5), 'Z', 1),
            (Router('G', '10.0.0.7', .5, .5), 'F', 0),
            (Router('G', '10.0.0.7', .5, .5), 'F', True),
            (Router('G', '10.0.0.7', math.nan, .5), None, 1),
            (Router('G', '10.0.0.7', .5, 1.1), None, 1),
        ]
        for router, neighbor, cost in cases:
            with self.subTest(router=router, neighbor=neighbor, cost=cost):
                before = self.engine.export_data()
                with self.assertRaises(ValueError):
                    self.engine.add_router(router, neighbor, cost)
                self.assertEqual(self.engine.export_data(), before)

    def test_router_names_are_validated_and_multi_character_names_work(self):
        for name in ['', 'G-H', 'G H', '1G', 'G' * 13, '../G']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.engine.add_router(Router(name, '10.0.0.7', .5, .5))
        self.engine.add_router(Router('Router_7', '10.0.0.7', .5, .5), 'F', 3)
        self.engine.calculate_all()
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.path[-1], 'Router_7')
        self.assertEqual(packet.outcome, 'deliver')

    def test_invalid_links_do_not_partially_modify_model(self):
        for a, b, cost in [('A', 'A', 1), ('A', 'Z', 1), ('A', 'C', 1),
                            ('C', 'A', 1), ('A', 'F', 0), ('A', 'F', -1),
                            ('A', 'F', 1.5), ('A', 'F', True)]:
            with self.subTest(a=a, b=b, cost=cost):
                before = self.engine.export_data()
                with self.assertRaises(ValueError):
                    self.network.add_link(a, b, cost)
                self.assertEqual(self.engine.export_data(), before)

    def test_move_does_not_invalidate_tables_or_restart_spf(self):
        revision, runs = self.network.revision, self.engine.spf_runs
        self.network.move_router('F', .4, .5)
        self.assertEqual((self.network.routers['F'].x, self.network.routers['F'].y), (.4, .5))
        self.assertEqual(self.network.revision, revision)
        self.assertEqual(self.engine.spf_runs, runs)
        self.assertEqual(self.engine.table_status('A'), 'current')
        packet, _ = trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.total_cost, 10)

    def test_invalid_moves_leave_coordinates_unchanged(self):
        for x, y in [(math.inf, 0), (-.1, .5), (.5, 1.1), (True, .5), ('0.5', .5)]:
            with self.subTest(x=x, y=y):
                before = self.network.routers['A']
                with self.assertRaises(ValueError):
                    self.network.move_router('A', x, y)
                self.assertEqual(self.network.routers['A'], before)
        with self.assertRaises(ValueError):
            self.network.move_router('Z', .5, .5)

    def test_suggestion_is_unique_and_does_not_change_network(self):
        before = self.engine.export_data()
        suggestion = self.network.suggest_router()
        self.assertEqual(suggestion.name, 'G')
        self.assertEqual(suggestion.address, '10.0.0.7')
        self.assertEqual(self.engine.export_data(), before)
        self.engine.add_router(suggestion)
        self.assertEqual(self.network.suggest_router().name, 'H')
        self.assertEqual(self.network.suggest_router().address, '10.0.0.8')

    def test_suggestions_continue_after_z(self):
        for _ in range(20):
            self.engine.add_router(self.network.suggest_router())
        self.assertEqual(self.network.suggest_router().name, 'R1')
        self.engine.add_router(self.network.suggest_router())
        self.assertEqual(self.network.suggest_router().name, 'R2')

    def test_old_snapshot_cannot_be_installed_after_addition(self):
        revision = self.network.revision
        old = list(dijkstra_steps(self.network.adjacency(), 'A'))[-1]
        self.engine.add_router(Router('G', '10.0.0.7', .5, .5))
        with self.assertRaises(ValueError):
            self.engine.install(old, revision)

    def test_drawing_move_does_not_prevent_installing_spf(self):
        revision = self.network.revision
        result = list(dijkstra_steps(self.network.adjacency(), 'A'))[-1]
        self.network.move_router('A', .2, .3)
        self.engine.install(result, revision)
        self.assertEqual(self.engine.table_status('A'), 'current')

    def test_export_contains_added_nodes_links_and_positions(self):
        self.engine.add_router(Router('G', '10.0.0.7', .4, .7), 'F', 3)
        data = self.engine.export_data()
        self.assertEqual(data['routers']['G'], '10.0.0.7')
        self.assertEqual(data['positions']['G'], {'x': .4, 'y': .7})
        self.assertEqual(data['tables']['G']['status'], 'local only')
        self.assertEqual(len(data['links']), 10)

    def test_larger_graph_after_additions_matches_independent_reference(self):
        for seed in range(5):
            engine = RoutingEngine(make_default_network())
            rng = random.Random(seed)
            for _ in range(9):
                engine.add_router(engine.network.suggest_router())
            names = sorted(engine.network.routers)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    if (a, b) not in engine.network.links and rng.random() < .2:
                        engine.network.add_link(a, b, rng.randint(1, 20))
            engine.calculate_all()
            graph = engine.network.adjacency()
            self.assertEqual(engine.spf_runs, 15)
            for source in names:
                distance = {name: math.inf for name in names}
                distance[source] = 0
                for _ in range(len(names) - 1):
                    for a in names:
                        for b, cost in graph[a].items():
                            distance[b] = min(distance[b], distance[a] + cost)
                self.assertEqual(engine.results[source].distances, distance)
                for target in names:
                    packet, _ = trace_packet(engine, source, engine.network.routers[target].address, ttl=64)
                    if math.isinf(distance[target]):
                        self.assertEqual(packet.outcome, 'drop')
                    else:
                        self.assertEqual(packet.outcome, 'deliver')
                        self.assertEqual(packet.total_cost, distance[target])


@unittest.skipUnless(tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a graphical display for Tk checks.')
class TopologyEditorGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = RoutingDemo(self.root)
        self.root.update()

    def tearDown(self):
        if self.app.editor_window is not None:
            self.app.editor_window.cancel_form()
        self.app.close()
        self.assertEqual(self.errors, [])

    def add_g(self, neighbor='F'):
        dialog = self.app.add_router_dialog()
        dialog.form_values['neighbor'].set(neighbor)
        dialog.form_values['cost'].set('3')
        dialog.submit_form()
        self.root.update()
        self.assertIn('G', self.app.network.routers)

    def test_add_router_updates_every_selector_and_packet_destination(self):
        self.app.build_all()
        self.add_g()
        for selector in self.app.router_selectors:
            self.assertIn('G', selector['values'])
        self.assertEqual(self.app.packet_target.get(), 'G')
        self.assertEqual(self.app.destination_ip.get(), '10.0.0.7')
        self.assertEqual(self.app.engine.table_status('A'), 'STALE')
        self.assertIn('F-G', self.app.link_selector['values'])
        self.app.build_all()
        self.assertIn('7/7', self.app.status_text.get())
        self.assertEqual(len(self.app.all_tree.get_children()), 49)
        packet, _ = trace_packet(self.app.engine, 'A', '10.0.0.7')
        self.assertEqual(packet.total_cost, 13)

    def test_add_link_form_connects_an_isolated_router(self):
        self.add_g('(none)')
        self.app.build_all()
        self.assertNotIn('G', self.app.engine.tables['A'])
        dialog = self.app.add_link_dialog()
        dialog.form_values['a'].set('F')
        dialog.form_values['b'].set('G')
        dialog.form_values['cost'].set('3')
        dialog.submit_form()
        self.root.update()
        self.assertIn(('F', 'G'), self.app.network.links)
        self.app.build_all()
        self.assertEqual(self.app.engine.tables['A']['G'].cost, 13)

    def test_invalid_dialog_and_cancel_preserve_graph(self):
        self.app.build_all()
        before = self.app.engine.export_data()
        dialog = self.app.add_router_dialog()
        dialog.form_values['name'].set('A')
        dialog.submit_form()
        self.root.update()
        self.assertTrue(dialog.form_error.get())
        self.assertEqual(self.app.engine.export_data(), before)
        dialog.cancel_form()
        self.assertEqual(self.app.engine.export_data(), before)

    def test_duplicate_link_is_rejected_in_form(self):
        before = self.app.engine.export_data()
        dialog = self.app.add_link_dialog()
        dialog.form_values['a'].set('C')
        dialog.form_values['b'].set('A')
        dialog.submit_form()
        self.assertIn('already exists', dialog.form_error.get())
        self.assertEqual(self.app.engine.export_data(), before)

    def test_click_position_and_drag_keep_routes_current(self):
        self.app._add_router_at_click(SimpleNamespace(x=self.app.canvas.winfo_width() // 2, y=40))
        self.assertIsNotNone(self.app.editor_window)
        self.app.editor_window.submit_form()
        self.root.update()
        self.app.build_all()
        revision = self.app.network.revision
        x, y = self.app._positions()['G']
        self.app.canvas.event_generate('<ButtonPress-1>', x=int(x), y=int(y), time=1000)
        self.root.update()
        self.app.canvas.event_generate('<B1-Motion>', x=int(x + 50), y=int(y + 30), time=1100)
        self.root.update()
        self.app.canvas.event_generate('<ButtonRelease-1>', x=int(x + 50), y=int(y + 30), time=1200)
        self.root.update()
        nx, ny = self.app._positions()['G']
        self.assertGreater(nx, x + 40)
        self.assertGreater(ny, y + 20)
        self.assertEqual(self.app.network.revision, revision)
        self.assertEqual(self.app.engine.table_status('A'), 'current')
        self.assertIsNone(self.app.drag_router)
        self.app._add_router_at_click(SimpleNamespace(x=nx, y=ny))
        self.assertIsNone(self.app.editor_window)  # Double-clicking G must not create H.

    def test_addition_cancels_incomplete_spf_and_pending_packet(self):
        self.app.animate_all()
        self.assertTrue(self.app.spf_auto)
        self.add_g()
        self.assertFalse(self.app.spf_auto)
        self.assertIsNone(self.app.iterator)
        self.assertEqual(list(self.app.spf_queue), [])
        self.assertIsNone(self.app.spf_job)
        self.app.build_all()
        self.app.new_packet()
        self.app.toggle_packet()
        dialog = self.app.add_router_dialog()
        dialog.submit_form()
        self.root.update()
        self.assertIn('H', self.app.network.routers)
        self.assertIsNone(self.app.packet)
        self.assertIsNone(self.app.packet_job)
        self.assertIsNone(self.app.frame_job)

    def test_reset_confirmation_and_dynamic_selector_cleanup(self):
        self.add_g()
        with patch('dijkstra_routing_demo.messagebox.askyesno', return_value=False):
            self.app.reset_network()
        self.assertIn('G', self.app.network.routers)
        with patch('dijkstra_routing_demo.messagebox.askyesno', return_value=True):
            self.app.reset_network()
        self.root.update()
        for selector in self.app.router_selectors:
            self.assertNotIn('G', selector['values'])
        self.assertNotIn('F-G', self.app.link_selector['values'])
        self.assertEqual(self.app.packet_target.get(), 'F')
        self.assertEqual(self.app.destination_ip.get(), '10.0.0.6')
        self.assertEqual(len(self.app.all_tree.get_children()), 6)

    def test_many_nodes_scroll_to_the_selected_route(self):
        for _ in range(12):
            node = self.app.network.suggest_router()
            self.app.engine.add_router(node, 'F', 1)
        self.app._topology_changed('Test expansion.')
        self.app.build_all()
        self.app.packet_target.set('R')
        self.app.select_target()
        self.app.new_packet()
        self.app._packet_hop()
        self.root.update()
        self.assertEqual(self.app.route_tree.selection(), ('R',))
        self.assertGreater(self.app.route_tree.yview()[0], 0)
        self.assertEqual(len(self.app.route_tree.get_children()), 18)
        self.assertIn('18/18', self.app.status_text.get())

    def test_packet_animation_delivers_to_added_router(self):
        self.add_g()
        self.app.build_all()
        self.app.speed.set(.001)
        self.app.new_packet()
        self.app.toggle_packet()
        deadline = time.monotonic() + 5
        while self.app.packet is not None and not self.app.packet.done and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)
        self.assertTrue(self.app.packet.done)
        self.assertEqual(self.app.packet.outcome, 'deliver')
        self.assertEqual(self.app.packet.path, list('ACBDEFG'))
        self.assertEqual(self.app.packet.total_cost, 13)
        self.assertEqual(self.app.engine.spf_runs, 7)

    def test_overlapping_routers_do_not_break_packet_arrow(self):
        self.add_g()
        f = self.app.network.routers['F']
        self.app.network.move_router('G', f.x, f.y)
        self.app.build_all()
        self.app.packet_position = ('F', 'G', .5)
        self.app.new_packet()
        self.app.packet_position = ('F', 'G', .5)
        self.app.draw_network()
        self.root.update()


if __name__ == '__main__':
    unittest.main()
