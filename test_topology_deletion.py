# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Structural deletion: model safety, route invalidation and real-Tk workflows."""
from copy import deepcopy
import math
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import dijkstra_routing_demo as demo


class TopologyDeletionTests(unittest.TestCase):
    def setUp(self):
        self.network = demo.make_default_network()
        self.engine = demo.RoutingEngine(self.network)
        self.engine.calculate_all()

    def assert_local_only(self):
        self.assertEqual(set(self.engine.tables), set(self.network.routers))
        self.assertEqual(set(self.engine.versions), set(self.network.routers))
        self.assertEqual(self.engine.results, {})
        for name, router in self.network.routers.items():
            self.assertEqual(list(self.engine.tables[name]), [name])
            route = self.engine.tables[name][name]
            self.assertEqual(route.prefix, router.prefix)
            self.assertIsNone(route.next_hop)
            self.assertEqual(route.cost, 0)
            self.assertIsNone(self.engine.versions[name])

    def test_remove_router_removes_all_incident_links_in_one_revision(self):
        before = self.network.revision
        removed = self.network.remove_router('D')
        self.assertEqual(removed, (('B', 'D'), ('C', 'D'), ('D', 'E'), ('D', 'F')))
        self.assertNotIn('D', self.network.routers)
        self.assertEqual(self.network.revision, before + 1)
        self.assertTrue(all('D' not in key for key in self.network.links))
        self.assertTrue(all('D' not in neighbors for neighbors in self.network.adjacency().values()))

    def test_unknown_router_requests_are_atomic(self):
        before = deepcopy(self.engine.export_data())
        for name in ('missing', '', None, []):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.engine.remove_router(name)
            self.assertEqual(self.engine.export_data(), before)

    def test_remove_link_accepts_reversed_endpoints_and_keeps_nodes(self):
        routers = self.network.routers.copy()
        revision = self.network.revision
        self.network.remove_link('E', 'D')
        self.assertNotIn(('D', 'E'), self.network.links)
        self.assertEqual(self.network.routers, routers)
        self.assertNotIn('E', self.network.adjacency()['D'])
        self.assertNotIn('D', self.network.adjacency()['E'])
        self.assertEqual(self.network.revision, revision + 1)

    def test_invalid_link_requests_do_not_touch_routes_or_topology(self):
        before = deepcopy(self.engine.export_data())
        for a, b in [('A', 'A'), ('A', 'F'), ('A', 'missing'), (None, 'B'), ([], 'B')]:
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                self.engine.remove_link(a, b)
            self.assertEqual(self.engine.export_data(), before)

    def test_repeated_deletion_does_not_increment_revision_twice(self):
        self.engine.remove_link('D', 'E')
        revision = self.network.revision
        with self.assertRaises(ValueError):
            self.engine.remove_link('D', 'E')
        self.assertEqual(self.network.revision, revision)
        self.engine.remove_router('D')
        revision = self.network.revision
        with self.assertRaises(ValueError):
            self.engine.remove_router('D')
        self.assertEqual(self.network.revision, revision)

    def test_both_engine_removals_clear_computed_state_without_spf(self):
        for kind in ('router', 'link'):
            with self.subTest(kind=kind):
                self.setUp()
                runs = self.engine.spf_runs
                with patch.object(demo, 'dijkstra_steps', side_effect=AssertionError('Unexpected SPF')):
                    if kind == 'router':
                        self.engine.remove_router('D')
                    else:
                        self.engine.remove_link('D', 'E')
                self.assert_local_only()
                self.assertEqual(self.engine.spf_runs, runs)

    def test_last_router_can_be_removed_and_empty_graph_saved(self):
        for name in list(self.network.routers):
            self.engine.remove_router(name)
        self.assert_local_only()
        self.assertEqual(self.network.adjacency(), {})
        self.assertEqual(self.network.links, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.graph.json'
            demo.save_graph_file(self.network, path)
            loaded = demo.load_graph_file(path)
            self.assertEqual((loaded.routers, loaded.links), ({}, {}))

    def test_old_spf_snapshot_cannot_be_installed_after_deletion(self):
        old_result = self.engine.results['D']
        revision = self.network.revision
        self.engine.remove_router('D')
        with self.assertRaises(ValueError):
            self.engine.install(old_result, revision)
        self.assert_local_only()

    def test_deleted_source_is_rejected_and_old_destination_is_no_route(self):
        self.engine.remove_router('F')
        with self.assertRaises(ValueError):
            demo.trace_packet(self.engine, 'F', '10.0.0.1')
        self.engine.calculate_all()
        packet, decisions = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.outcome, 'drop')
        self.assertEqual(decisions[-1].reason_code, 'NO_ROUTE')
        self.assertEqual(packet.ttl, 16)

    def test_rebuild_after_link_deletion_finds_alternative(self):
        self.engine.remove_link('D', 'E')
        self.assert_local_only()
        self.engine.calculate_all()
        with patch.object(demo, 'dijkstra_steps', side_effect=AssertionError('SPF during forwarding')):
            packet, _ = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, list('ACEF'))
        self.assertEqual((packet.outcome, packet.total_cost), ('deliver', 11))

    def test_rebuild_after_router_deletion_avoids_deleted_node(self):
        self.engine.remove_router('C')
        self.engine.calculate_all()
        packet, _ = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, list('ABDEF'))
        self.assertEqual((packet.outcome, packet.total_cost), ('deliver', 12))
        self.assertTrue(all('C' not in step.distances for step in self.engine.results.values()))

    def test_deleting_final_connection_leaves_destination_isolated(self):
        self.engine.remove_link('D', 'F')
        self.engine.remove_link('E', 'F')
        self.engine.calculate_all()
        packet, decisions = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.outcome, 'drop')
        self.assertEqual(decisions[-1].reason_code, 'NO_ROUTE')
        self.assertIn('F', self.network.routers)
        packet, _ = demo.trace_packet(self.engine, 'F', '10.0.0.6', ttl=1)
        self.assertEqual((packet.outcome, packet.ttl), ('deliver', 1))

    def test_readd_deleted_router_and_link_has_no_ghost_state(self):
        self.engine.remove_router('F')
        self.engine.add_router(demo.Router('F', '10.0.0.6', .8, .4), 'A', 1)
        self.engine.calculate_all()
        packet, _ = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, ['A', 'F'])
        self.assertEqual(packet.total_cost, 1)
        self.engine.remove_link('A', 'F')
        self.network.add_link('A', 'F', 4)
        self.engine.calculate_all()
        packet, _ = demo.trace_packet(self.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.total_cost, 4)
        self.assertEqual(self.network.adjacency()['F'], {'A': 4})

    def test_persistence_round_trip_preserves_deletions_and_remaining_layout(self):
        self.network.move_router('B', .123, .456)
        self.engine.remove_router('C')
        self.engine.remove_link('D', 'E')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deleted.graph.json'
            demo.save_graph_file(self.network, path)
            loaded = demo.load_graph_file(path)
        self.assertEqual(demo.graph_to_data(loaded), demo.graph_to_data(self.network))
        self.assertEqual((loaded.routers['B'].x, loaded.routers['B'].y), (.123, .456))
        self.assertNotIn('C', loaded.routers)
        self.assertNotIn(('D', 'E'), loaded.links)

    def test_seeded_deletion_sequences_against_bellman_ford(self):
        # Compare all sources and all packet routes after every random deletion.
        for seed in range(8):
            rng = random.Random(seed)
            network = demo.make_default_network()
            engine = demo.RoutingEngine(network)
            while network.routers:
                if network.links and rng.random() < .5:
                    engine.remove_link(*rng.choice(list(network.links)))
                else:
                    engine.remove_router(rng.choice(list(network.routers)))
                engine.calculate_all()
                graph = network.adjacency()
                for source in graph:
                    distances = {name: math.inf for name in graph}
                    distances[source] = 0
                    for _ in range(max(0, len(graph) - 1)):
                        for a, neighbors in graph.items():
                            for b, cost in neighbors.items():
                                distances[b] = min(distances[b], distances[a] + cost)
                    self.assertEqual(engine.results[source].distances, distances)
                    for target, router in network.routers.items():
                        packet, _ = demo.trace_packet(engine, source, router.address)
                        if math.isinf(distances[target]):
                            self.assertEqual(packet.outcome, 'drop')
                        else:
                            self.assertEqual(packet.outcome, 'deliver')
                            self.assertEqual(packet.total_cost, distances[target])


@unittest.skipUnless(demo.tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a display for Tk checks.')
class TopologyDeletionGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'saved.graph.json'
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
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=False):
            self.app.close()
        self.assertEqual(self.errors, [])

    def assert_no_simulation(self):
        self.root.update()
        for field in ('step', 'iterator', 'packet', 'spf_job', 'packet_job', 'frame_job',
                      'packet_position', 'lookup_router', 'highlight_prefix', 'last_decision', 'drag_router'):
            self.assertIsNone(getattr(self.app, field), field)
        self.assertEqual(self.app.trace_decisions, {})
        self.assertEqual(self.app.trace_tree.get_children(), ())
        self.assertEqual(list(self.app.spf_queue), [])
        self.assertFalse(self.app.spf_auto)
        self.assertFalse(self.app.packet_auto)
        self.assertFalse(self.app.packet_animating)

    def test_router_button_targets_inspected_node_and_lists_its_links(self):
        self.app.inspect_router('D')
        with patch.object(demo.messagebox, 'askyesno', return_value=True) as confirm:
            self.app.delete_router_button.invoke()
        self.root.update()
        self.assertIn('D (10.0.0.4/32)', confirm.call_args.args[1])
        self.assertIn('4 attached link', confirm.call_args.args[1])
        self.assertEqual(confirm.call_args.kwargs['default'], 'no')
        self.assertNotIn('D', self.app.network.routers)
        self.assertTrue(all('D' not in key for key in self.app.network.links))
        self.assertNotIn('D', self.app.work_tree.get_children())
        self.assertTrue(self.app.has_unsaved_graph())

    def test_link_button_deletes_selected_link_but_preserves_both_nodes(self):
        self.app.select_link(('D', 'E'))
        with patch.object(demo.messagebox, 'askyesno', return_value=True) as confirm:
            self.app.delete_link_button.invoke()
        self.assertIn('D-E (cost 1)', confirm.call_args.args[1])
        self.assertNotIn(('D', 'E'), self.app.network.links)
        self.assertTrue({'D', 'E'} <= self.app.network.routers.keys())
        self.assertNotIn('D-E', self.app.link_selector.cget('values'))
        self.assertTrue(self.app.has_unsaved_graph())

    def test_edit_menu_dispatches_both_actions(self):
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.inspect_router('F')
            self.app.edit_menu.invoke(0)
            self.assertNotIn('F', self.app.network.routers)
            self.app.select_link(('D', 'E'))
            self.app.edit_menu.invoke(1)
            self.assertNotIn(('D', 'E'), self.app.network.links)

    def test_cancel_deletion_preserves_network_tables_file_and_packet(self):
        self.app.build_all()
        self.app.graph_file = self.path
        self.app.new_packet()
        packet = self.app.packet
        before = deepcopy(self.app.engine.export_data())
        saved = self.app.saved_graph
        for callback in (self.app.delete_router, self.app.delete_link):
            with patch.object(demo.messagebox, 'askyesno', return_value=False):
                self.assertFalse(callback())
            self.assertEqual(self.app.engine.export_data(), before)
            self.assertIs(self.app.packet, packet)
            self.assertIs(self.app.saved_graph, saved)
            self.assertEqual(self.app.graph_file, self.path)
            self.assertFalse(self.app.has_unsaved_graph())

    def test_cancel_while_spf_is_running_keeps_iterator_and_queue(self):
        self.app.animate_all()
        iterator = self.app.iterator
        queue = list(self.app.spf_queue)
        step = self.app.step
        with patch.object(demo.messagebox, 'askyesno', return_value=False):
            self.assertFalse(self.app.delete_router())
        self.assertIs(self.app.iterator, iterator)
        self.assertIs(self.app.step, step)
        self.assertEqual(list(self.app.spf_queue), queue)
        self.assertFalse(self.app.spf_auto)
        self.assertIsNone(self.app.spf_job)
        self.app.toggle_spf()
        self.assertTrue(self.app.spf_auto)

    def test_deletion_during_spf_cancels_old_callbacks_and_clears_routes(self):
        self.app.build_all()
        self.app.animate_all()
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.assertTrue(self.app.delete_router())
        self.assert_no_simulation()
        self.assertTrue(all(list(table) == [router] for router, table in self.app.engine.tables.items()))
        self.assertEqual(self.app.engine.results, {})

    def test_deletion_during_packet_animation_clears_old_packet_and_trace(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.step_packet()
        self.assertTrue(self.app.packet_animating)
        self.app.inspect_router('C')  # The just-selected next hop is deleted.
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_router()
        self.assert_no_simulation()
        self.assertNotIn('C', self.app.network.routers)
        self.assertIn('Computed routes cleared', self.app.log_text.get('1.0', 'end'))

    def test_last_router_deletion_disables_controls_and_shows_empty_graph(self):
        self.app._install_graph(demo.Network([demo.Router('Solo', '192.0.2.1', .5, .5)], []))
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.assertTrue(self.app.delete_router())
        self.assert_no_simulation()
        self.assertEqual(self.app.network.routers, {})
        self.assertEqual(self.app.engine.tables, {})
        for selector in self.app.router_selectors:
            self.assertEqual(selector.get(), '')
            self.assertTrue(selector.instate(['disabled']))
        self.assertTrue(self.app.delete_router_button.instate(['disabled']))
        self.assertTrue(self.app.delete_link_button.instate(['disabled']))
        self.assertTrue(self.app.topology_buttons['Add link'].instate(['disabled']))
        self.assertTrue(self.app.canvas.find_withtag('empty_hint'))
        self.assertEqual(self.app.destination_ip.get(), '')
        self.assertEqual(self.app.route_tree.get_children(), ())

    def test_empty_controls_callbacks_and_invalid_selection_do_not_prompt(self):
        self.app._install_graph(demo.Network([], []))
        with patch.object(demo.messagebox, 'askyesno') as confirm:
            self.assertFalse(self.app.delete_router())
            self.assertFalse(self.app.delete_link())
            confirm.assert_not_called()
        self.assertEqual(self.app.edit_menu.entrycget(0, 'state'), 'disabled')
        self.assertEqual(self.app.edit_menu.entrycget(1, 'state'), 'disabled')
        self.app.reset_network()
        self.app.inspector.set('missing')
        self.app.link_name.set('missing')
        with patch.object(demo.messagebox, 'askyesno') as confirm:
            self.assertFalse(self.app.delete_router())
            self.assertFalse(self.app.delete_link())
            confirm.assert_not_called()
        self.app._refresh_selectors()

    def test_last_link_deletion_disables_editor_but_not_routers(self):
        self.app._install_graph(demo.Network([
            demo.Router('Left', '192.0.2.1', .2, .5), demo.Router('Right', '192.0.2.2', .8, .5)
        ], [demo.Link('Left', 'Right', 3)]))
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.assertTrue(self.app.delete_link())
        self.assertEqual(self.app.network.links, {})
        self.assertTrue(self.app.delete_link_button.instate(['disabled']))
        self.assertTrue(self.app.apply_link_button.instate(['disabled']))
        self.assertFalse(self.app.delete_router_button.instate(['disabled']))
        self.assertFalse(self.app.topology_buttons['Add link'].instate(['disabled']))

    def test_deleting_source_root_target_repairs_selectors_and_destination_ip(self):
        for variable in (self.app.spf_root, self.app.packet_source, self.app.packet_target):
            variable.set('F')
        self.app.select_target()
        self.app.inspect_router('F')
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_router()
        for selector in self.app.router_selectors:
            self.assertNotIn('F', selector.cget('values'))
            self.assertIn(selector.get(), self.app.network.routers)
        self.assertEqual(self.app.destination_ip.get(), self.app.network.routers[self.app.packet_target.get()].address)

    def test_surviving_target_keeps_custom_destination_input(self):
        self.app.packet_target.set('F')
        self.app.destination_ip.set('10.99.0.1')
        self.app.inspect_router('D')
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_router()
        self.assertEqual(self.app.packet_target.get(), 'F')
        self.assertEqual(self.app.destination_ip.get(), '10.99.0.1')

    def test_file_stays_unchanged_until_explicit_save(self):
        self.app.graph_file = self.path
        self.assertTrue(self.app.save_graph())
        original = self.path.read_bytes()
        self.app.inspect_router('C')
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_router()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.app.graph_file, self.path)
        self.assertTrue(self.app.has_unsaved_graph())
        self.assertIn('*', self.root.title())
        self.assertTrue(self.app.save_graph())
        self.assertFalse(self.app.has_unsaved_graph())
        self.assertNotIn('C', demo.load_graph_file(self.path).routers)

    def test_delete_save_load_and_forward_recomputes_the_expected_route(self):
        self.app.select_link(('D', 'E'))
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_link()
        self.app.graph_file = self.path
        self.assertTrue(self.app.save_graph())
        self.app.reset_network()
        with patch.object(demo.filedialog, 'askopenfilename', return_value=str(self.path)):
            self.assertTrue(self.app.load_graph())
        self.app.build_all()
        packet, _ = demo.trace_packet(self.app.engine, 'A', '10.0.0.6')
        self.assertEqual(packet.path, list('ACEF'))
        self.assertEqual(packet.total_cost, 11)

    def test_readding_after_last_deletion_restores_controls(self):
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            while self.app.network.routers:
                self.app.delete_router()
        form = self.app.add_router_dialog()
        self.assertEqual(form.form_values['name'].get(), 'A')
        form.submit_form()
        self.root.update()
        self.assertFalse(self.app.delete_router_button.instate(['disabled']))
        self.assertIn('A', self.app.engine.tables)
        self.assertEqual(self.app.packet_target.get(), 'A')
        self.assertEqual(self.app.destination_ip.get(), '10.0.0.1')

    def test_modal_about_and_editor_prevent_deletion(self):
        for open_dialog in (self.app.show_about, self.app.add_router_dialog):
            dialog = open_dialog()
            before = demo.graph_to_data(self.app.network)
            with patch.object(demo.messagebox, 'askyesno') as confirm:
                self.assertFalse(self.app.delete_router())
                self.assertFalse(self.app.delete_link())
                confirm.assert_not_called()
            self.assertEqual(self.root.grab_current(), dialog)
            self.assertEqual(demo.graph_to_data(self.app.network), before)
            if self.app.about_window is not None:
                self.app.close_about()
            else:
                dialog.cancel_form()

    def test_link_up_remains_a_distinct_failure_experiment(self):
        self.app.build_all()
        self.app.select_link(('D', 'E'))
        self.app.link_up.set(False)
        self.app.apply_link()
        self.assertIn(('D', 'E'), self.app.network.links)
        self.assertEqual(self.app.engine.table_status('A'), 'STALE')
        packet, decisions = demo.trace_packet(self.app.engine, 'A', '10.0.0.6')
        self.assertEqual(decisions[-1].reason_code, 'LINK_DOWN')
        self.assertEqual(packet.path, list('ACBD'))
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_link()
        self.assertNotIn(('D', 'E'), self.app.network.links)
        self.assertEqual(self.app.engine.table_status('A'), 'local only')

    def test_compact_layout_shows_both_delete_buttons_and_all_toolbar_actions(self):
        self.root.geometry('1180x740')
        self.root.update()
        for widget in (self.app.delete_router_button, self.app.delete_link_button,
                       *self.app.topology_buttons.values()):
            with self.subTest(button=widget.cget('text')):
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreater(widget.winfo_width(), 50)
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                     self.root.winfo_rootx() + self.root.winfo_width())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                     self.root.winfo_rooty() + self.root.winfo_height())

    def test_save_prompt_protects_deleted_topology_on_new(self):
        with patch.object(demo.messagebox, 'askyesno', return_value=True):
            self.app.delete_router()
        before = demo.graph_to_data(self.app.network)
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=None) as confirm:
            self.assertFalse(self.app.new_topology())
            confirm.assert_called_once()
        self.assertEqual(demo.graph_to_data(self.app.network), before)

    def test_selected_router_not_destination_row_is_deleted(self):
        self.app.build_all()
        self.app.inspect_router('A')
        self.app.route_tree.selection_set('F')
        with patch.object(demo.messagebox, 'askyesno', return_value=True) as confirm:
            self.app.delete_router()
        self.assertIn('router A ', confirm.call_args.args[1])
        self.assertIn('F', self.app.network.routers)
        self.assertNotIn('A', self.app.network.routers)


if __name__ == '__main__':
    unittest.main()
