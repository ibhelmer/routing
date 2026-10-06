# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Empty-topology model tests and opt-in real-Tk workflow regression tests."""
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dijkstra_routing_demo as demo


def interactive_children(parent):
    for child in parent.winfo_children():
        if isinstance(child, (demo.ttk.Button, demo.ttk.Entry, demo.ttk.Combobox,
                              demo.ttk.Checkbutton, demo.ttk.Scale)):
            yield child
        yield from interactive_children(child)


class EmptyTopologyTests(unittest.TestCase):
    def test_empty_network_and_engine_have_no_invented_nodes_or_tables(self):
        network = demo.Network([], [])
        self.assertEqual(network.adjacency(), {})
        engine = demo.RoutingEngine(network)
        engine.calculate_all()
        self.assertEqual((engine.tables, engine.versions, engine.results, engine.spf_runs), ({}, {}, {}, 0))

    def test_first_router_suggestion_is_centered_and_nonmutating(self):
        network = demo.Network([], [])
        suggestion = network.suggest_router()
        self.assertEqual(suggestion, demo.Router('A', '10.0.0.1', .5, .5))
        self.assertEqual(network.routers, {})
        engine = demo.RoutingEngine(network)
        engine.add_router(suggestion)
        self.assertEqual(network.suggest_router().name, 'B')
        self.assertEqual(network.suggest_router().address, '10.0.0.2')

    def test_empty_graph_serialization_round_trip(self):
        network = demo.Network([], [])
        data = demo.graph_to_data(network)
        self.assertEqual(data, {'format': demo.GRAPH_FORMAT, 'version': demo.GRAPH_VERSION,
                                'routers': [], 'links': []})
        self.assertEqual(demo.graph_to_data(demo.graph_from_data(data)), data)

    def test_save_and_load_empty_graph_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tom_topologi.graph.json'
            demo.save_graph_file(demo.Network([], []), path)
            loaded = demo.load_graph_file(path)
            self.assertEqual((loaded.routers, loaded.links), ({}, {}))
            self.assertEqual(json.loads(path.read_text())['routers'], [])

    def test_empty_export_with_and_without_positions_can_be_loaded(self):
        data = demo.RoutingEngine(demo.Network([], [])).export_data()
        for document in (data, {k: v for k, v in data.items() if k != 'positions'}):
            with self.subTest(positions='positions' in document):
                self.assertEqual(demo.graph_from_data(document).routers, {})

    def test_empty_nodes_with_links_are_still_invalid(self):
        link = demo.Link('A', 'B', 1)
        with self.assertRaises(ValueError):
            demo.Network([], [link])
        data = demo.graph_to_data(demo.Network([], []))
        data['links'] = [{'a': 'A', 'b': 'B', 'cost': 1, 'enabled': True}]
        with self.assertRaises(ValueError):
            demo.graph_from_data(data)

    def test_invalid_first_connection_does_not_partially_create_router(self):
        engine = demo.RoutingEngine(demo.Network([], []))
        with self.assertRaises(ValueError):
            engine.add_router(engine.network.suggest_router(), 'missing', 1)
        self.assertEqual(engine.network.routers, {})
        self.assertEqual(engine.tables, {})
        self.assertEqual(engine.network.revision, 1)

    def test_custom_network_routes_after_starting_empty(self):
        engine = demo.RoutingEngine(demo.Network([], []))
        engine.add_router(demo.Router('Core', '192.0.2.1', .2, .5))
        engine.add_router(demo.Router('Transit', '192.0.2.2', .5, .2), 'Core', 2)
        engine.add_router(demo.Router('Edge', '192.0.2.3', .8, .5), 'Transit', 3)
        engine.network.add_link('Core', 'Edge', 10)
        engine.calculate_all()
        with patch.object(demo, 'dijkstra_steps', side_effect=AssertionError('SPF during forwarding')):
            packet, _ = demo.trace_packet(engine, 'Core', '192.0.2.3')
        self.assertEqual(packet.path, ['Core', 'Transit', 'Edge'])
        self.assertEqual((packet.outcome, packet.total_cost, packet.ttl), ('deliver', 5, 14))

    def test_first_isolated_router_can_receive_its_own_packet(self):
        engine = demo.RoutingEngine(demo.Network([], []))
        engine.add_router(engine.network.suggest_router())
        packet, _ = demo.trace_packet(engine, 'A', '10.0.0.1', ttl=1)
        self.assertEqual((packet.outcome, packet.ttl), ('deliver', 1))

    def test_dijkstra_still_rejects_unknown_root_on_empty_graph(self):
        with self.assertRaises(ValueError):
            list(demo.dijkstra_steps({}, 'A'))


@unittest.skipUnless(demo.tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a display for Tk tests.')
class NewTopologyGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'previous.graph.json'
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

    def assert_empty(self):
        self.root.update()
        app = self.app
        self.assertEqual(app.network.routers, {})
        self.assertEqual(app.network.links, {})
        self.assertEqual(app.engine.tables, {})
        self.assertEqual(app.engine.spf_runs, 0)
        self.assertIsNone(app.graph_file)
        self.assertFalse(app.has_unsaved_graph())
        self.assertIsNone(app.step)
        self.assertIsNone(app.iterator)
        self.assertIsNone(app.packet)
        self.assertIsNone(app.last_decision)
        self.assertIsNone(app.lookup_router)
        self.assertIsNone(app.highlight_prefix)
        self.assertEqual(app.trace_decisions, {})
        for tree in (app.work_tree, app.route_tree, app.all_tree, app.trace_tree):
            self.assertEqual(tree.get_children(), ())
        for value in (app.spf_root, app.inspector, app.packet_source, app.packet_target,
                      app.destination_ip, app.link_name):
            self.assertEqual(value.get(), '')
        self.assertIn('empty topology', app.status_text.get())
        self.assertTrue(app.canvas.find_withtag('empty_hint'))
        self.assertFalse(any(tag.startswith(('router_', 'link_'))
                             for item in app.canvas.find_all() for tag in app.canvas.gettags(item)))

    def add_router(self, name, address, neighbor='(none)', cost='1'):
        dialog = self.app.add_router_dialog()
        for key, value in {'name': name, 'address': address, 'neighbor': neighbor, 'cost': cost}.items():
            dialog.form_values[key].set(value)
        dialog.submit_form()
        self.root.update()
        self.assertIsNone(self.app.editor_window)

    def test_button_clears_graph_routes_trace_and_current_packet(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.step_packet()
        self.app.topology_buttons['New topology'].invoke()
        self.assert_empty()

    def test_file_menu_and_ctrl_n_start_empty_without_inserting_defaults(self):
        self.app.file_menu.invoke('New topology')
        self.assert_empty()
        self.app.reset_network()
        self.root.update()
        self.root.focus_force()
        self.root.event_generate('<Control-n>')
        self.root.update()
        self.assert_empty()

    def test_unsaved_cancel_preserves_graph_packet_and_file_association(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.network.move_router('A', .22, .33)
        self.app.graph_file = self.path
        network, engine, packet = self.app.network, self.app.engine, self.app.packet
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=None) as ask:
            self.assertFalse(self.app.new_topology())
            ask.assert_called_once()
        self.assertIs(self.app.network, network)
        self.assertIs(self.app.engine, engine)
        self.assertIs(self.app.packet, packet)
        self.assertEqual(self.app.graph_file, self.path)
        self.assertTrue(self.app.has_unsaved_graph())

    def test_discard_starts_empty_without_touching_previous_saved_file(self):
        demo.save_graph_file(self.app.network, self.path)
        original = self.path.read_bytes()
        self.app.graph_file = self.path
        self.app.network.move_router('A', .22, .33)
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=False):
            self.assertTrue(self.app.new_topology())
        self.assert_empty()
        self.assertEqual(self.path.read_bytes(), original)

    def test_yes_saves_current_edits_before_starting_empty(self):
        self.app.network.move_router('A', .22, .33)
        previous = demo.graph_to_data(self.app.network)
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=True):
            with patch.object(demo.filedialog, 'asksaveasfilename', return_value=str(self.path)):
                self.assertTrue(self.app.new_topology())
        self.assert_empty()
        self.assertEqual(demo.graph_to_data(demo.load_graph_file(self.path)), previous)

    def test_cancelled_save_aborts_new_topology(self):
        self.app.network.move_router('A', .22, .33)
        network = self.app.network
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=True):
            with patch.object(demo.filedialog, 'asksaveasfilename', return_value=''):
                self.assertFalse(self.app.new_topology())
        self.assertIs(self.app.network, network)
        self.assertTrue(self.app.has_unsaved_graph())

    def test_failed_save_aborts_new_topology_and_retains_old_file(self):
        self.path.write_text('EXISTING FILE', encoding='utf-8')
        self.app.graph_file = self.path
        self.app.network.move_router('A', .22, .33)
        network = self.app.network
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=True):
            with patch.object(demo, 'save_graph_file', side_effect=OSError('disk full')):
                with patch.object(demo.messagebox, 'showerror') as error:
                    self.assertFalse(self.app.new_topology())
                    error.assert_called_once()
        self.assertIs(self.app.network, network)
        self.assertEqual(self.path.read_text(), 'EXISTING FILE')

    def test_empty_controls_disabled_and_guarded_callbacks_do_not_start_work(self):
        self.app.new_topology()
        for group in (self.app.spf_controls, self.app.packet_controls, self.app.link_controls):
            self.assertTrue(all(w.instate(['disabled']) for w in interactive_children(group)))
        self.assertTrue(all(w.instate(['disabled']) for w in self.app.router_selectors))
        self.assertTrue(self.app.topology_buttons['Add link'].instate(['disabled']))
        for action in (self.app.new_spf, self.app.step_spf, self.app.toggle_spf, self.app.finish_router,
                       self.app.animate_all, self.app.build_all, self.app.new_packet,
                       self.app.step_packet, self.app.toggle_packet, self.app.select_target):
            action()
        self.app.inspect_router('A')
        self.assert_empty()
        for job in ('spf_job', 'packet_job', 'frame_job'):
            self.assertIsNone(getattr(self.app, job))

    def test_first_router_enables_routing_but_not_link_creation(self):
        self.app.new_topology()
        self.add_router('Solo', '192.0.2.10')
        self.assertEqual(list(self.app.network.routers), ['Solo'])
        self.assertEqual(self.app.network.links, {})
        for group in (self.app.spf_controls, self.app.packet_controls):
            self.assertTrue(all(not w.instate(['disabled']) for w in interactive_children(group)))
        self.assertTrue(self.app.topology_buttons['Add link'].instate(['disabled']))
        self.assertTrue(self.app.has_unsaved_graph())
        self.assertEqual(self.app.packet_source.get(), 'Solo')
        self.assertEqual(self.app.destination_ip.get(), '192.0.2.10')
        self.assertFalse(self.app.canvas.find_withtag('empty_hint'))
        with patch.object(demo.messagebox, 'askyesnocancel') as ask:
            self.assertTrue(self.app.new_packet())
            self.app._packet_hop()
            ask.assert_not_called()
        self.assertEqual(self.app.packet.outcome, 'deliver')

    def test_double_click_on_empty_hint_opens_first_router_dialog(self):
        self.app.new_topology()
        self.root.update()
        hint = self.app.canvas.find_withtag('empty_hint')[0]
        x, y = self.app.canvas.coords(hint)
        self.app._add_router_at_click(SimpleNamespace(x=x, y=y))
        dialog = self.app.editor_window
        self.assertEqual(dialog.form_values['name'].get(), 'A')
        self.assertEqual(dialog.form_values['neighbor'].get(), '(none)')
        dialog.submit_form()
        self.assertEqual(list(self.app.network.routers), ['A'])

    def test_custom_two_router_link_routes_packet_without_original_nodes(self):
        self.app.new_topology()
        self.add_router('Source', '192.0.2.10')
        self.add_router('Sink', '192.0.2.20')
        self.assertFalse(self.app.topology_buttons['Add link'].instate(['disabled']))
        dialog = self.app.add_link_dialog()
        dialog.form_values['a'].set('Source')
        dialog.form_values['b'].set('Sink')
        dialog.form_values['cost'].set('4')
        dialog.submit_form()
        self.assertTrue(all(not w.instate(['disabled']) for w in interactive_children(self.app.link_controls)))
        self.app.build_all()
        self.app.packet_source.set('Source')
        self.app.packet_target.set('Sink')
        self.app.select_target()
        self.assertTrue(self.app.new_packet())
        self.app._packet_hop()
        self.app._cancel_job('frame_job')
        self.app._animate_edge('Source', 'Sink', time.monotonic() - 10, .12)
        self.app._packet_hop()
        self.assertEqual((self.app.packet.outcome, self.app.packet.total_cost), ('deliver', 4))
        self.assertEqual(self.app.packet.path, ['Source', 'Sink'])
        self.assertEqual(set(self.app.engine.tables), {'Source', 'Sink'})

    def test_new_empty_graph_can_be_saved_and_reopened(self):
        self.app.new_topology()
        with patch.object(demo.filedialog, 'asksaveasfilename', return_value=str(self.path)):
            self.assertTrue(self.app.save_graph())
        self.app.reset_network()
        with patch.object(demo.filedialog, 'askopenfilename', return_value=str(self.path)):
            self.assertTrue(self.app.load_graph())
        self.assertEqual(self.app.network.routers, {})
        self.assertEqual(self.app.graph_file, self.path)
        self.assertIn('Empty graph loaded', self.app.spf_note.get())
        self.add_router('First', '192.0.2.1')
        self.assertEqual(list(self.app.network.routers), ['First'])

    def test_new_detaches_old_file_and_next_save_chooses_new_path(self):
        with patch.object(demo.filedialog, 'asksaveasfilename', return_value=str(self.path)):
            self.app.save_graph()
        old = self.path.read_bytes()
        self.app.new_topology()
        new_path = self.path.with_name('new.graph.json')
        with patch.object(demo.filedialog, 'asksaveasfilename', return_value=str(new_path)) as dialog:
            self.app.save_graph()
            dialog.assert_called_once()
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.app.graph_file, new_path)
        self.assertEqual(demo.load_graph_file(new_path).routers, {})

    def test_reset_and_load_can_recover_from_empty_topology(self):
        demo.save_graph_file(self.app.network, self.path)
        self.app.new_topology()
        self.app.reset_network()
        self.assertEqual(set(self.app.network.routers), set('ABCDEF'))
        self.app.new_topology()
        with patch.object(demo.filedialog, 'askopenfilename', return_value=str(self.path)):
            self.assertTrue(self.app.load_graph())
        self.app.build_all()
        self.assertEqual(self.app.engine.spf_runs, 6)
        self.assertFalse(self.app.spf_play_button.instate(['disabled']))
        self.assertFalse(self.app.apply_link_button.instate(['disabled']))

    def test_new_cancels_queued_spf_callbacks(self):
        self.app.animate_all()
        job = self.app.spf_job
        self.assertIsNotNone(job)
        self.app.new_topology()
        self.assertNotIn(job, self.root.tk.call('after', 'info'))
        self.assertEqual(list(self.app.spf_queue), [])
        self.assertFalse(self.app.spf_auto)
        self.assert_empty()

    def test_new_cancels_packet_animation_callbacks(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.step_packet()
        self.app.packet_auto = True
        jobs = [self.app.frame_job]
        self.app.packet_job = self.root.after(10000, self.app._packet_hop)
        jobs.append(self.app.packet_job)
        self.app.new_topology()
        for job in jobs:
            self.assertNotIn(job, self.root.tk.call('after', 'info'))
        self.assertFalse(self.app.packet_auto)
        self.assertFalse(self.app.packet_animating)
        self.assert_empty()

    def test_cancel_keeps_unfinished_spf_iterator_and_queue(self):
        self.app.network.move_router('A', .22, .33)
        self.app.animate_all()
        iterator, queue = self.app.iterator, list(self.app.spf_queue)
        with patch.object(demo.messagebox, 'askyesnocancel', return_value=None):
            self.app.new_topology()
        self.assertIs(self.app.iterator, iterator)
        self.assertEqual(list(self.app.spf_queue), queue)
        self.assertTrue(self.app.has_unsaved_graph())
        self.assertFalse(self.app.spf_auto)

    def test_new_does_not_override_about_or_editor_modal(self):
        network = self.app.network
        about = self.app.show_about()
        self.assertFalse(self.app.new_topology())
        self.assertIs(self.root.grab_current(), about)
        self.app.close_about()
        editor = self.app.add_router_dialog()
        self.assertFalse(self.app.new_topology())
        self.assertIs(self.root.grab_current(), editor)
        self.assertIs(self.app.network, network)

    def test_repeated_new_is_clean_and_keeps_logos_and_about_available(self):
        for _ in range(3):
            self.assertTrue(self.app.new_topology())
            self.assert_empty()
        self.assertTrue(self.app.ihn_header.cget('image'))
        self.assertTrue(self.app.ucn_header.cget('image'))
        self.assertIsNotNone(self.app.show_about())
        self.app.close_about()
        self.assertFalse(self.app.has_unsaved_graph())

    def test_compact_window_shows_new_button_and_empty_graph_instructions(self):
        self.root.geometry('1180x740')
        self.app.new_topology()
        self.root.update()
        for button in self.app.topology_buttons.values():
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
        for item in self.app.canvas.find_withtag('empty_hint'):
            x1, y1, x2, y2 = self.app.canvas.bbox(item)
            self.assertGreaterEqual(y1, 0)
            self.assertLessEqual(y2, self.app.canvas.winfo_height())


if __name__ == '__main__':
    unittest.main()
