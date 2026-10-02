# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
"""Branding and About tests. GUI tests require RUN_GUI_TESTS=1 and a display."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dijkstra_routing_demo as demo


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class BrandingResourceTests(unittest.TestCase):
    def test_project_metadata_and_learning_purpose(self):
        self.assertEqual(demo.APP_NAME, 'Dijkstra Routing Lab')
        self.assertEqual(demo.REPOSITORY_URL, 'https://github.com/ibhelmer/routing')
        self.assertEqual(demo.__copyright__, 'Copyright 2026 Ib Helmer Nielsen')
        self.assertEqual(demo.__license__, 'Apache-2.0')
        content = ' '.join(body for heading, body in demo.ABOUT_SECTIONS)
        for term in ('Dijkstra', 'routing', 'packets', 'TTL', 'OSPF', 'save'):
            self.assertIn(term, content)

    def test_png_assets_have_the_expected_dimensions(self):
        for name, size in [('ihn-logo.png', (48, 48)), ('ihn-icon-16.png', (16, 16)),
                           ('ihn-icon-32.png', (32, 32)), ('ucn-logo.png', (104, 62))]:
            with self.subTest(name=name):
                data = (demo.ASSET_DIR / name).read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]), size)

    def test_original_user_logo_sources_are_preserved(self):
        for name, expected in [('ihn-logo.png', 'de32efd6300f4e9d0d652507904cd47993a129fc'),
                               ('ucn-logo.svg', 'b6bf0814fac12bb77a083b5f7201f94770f346d1')]:
            data = (demo.ASSET_DIR / name).read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            self.assertEqual(actual, expected)

    def test_windows_ico_contains_four_sizes(self):
        data = (demo.ASSET_DIR / 'ihn.ico').read_bytes()
        reserved, kind, count = struct.unpack('<HHH', data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 4))
        sizes = []
        for index in range(count):
            offset = 6 + 16 * index
            sizes.append((data[offset] or 256, data[offset + 1] or 256))
            length, start = struct.unpack_from('<II', data, offset + 8)
            self.assertGreater(length, 0)
            self.assertLessEqual(start + length, len(data))
        self.assertEqual(sizes, [(16, 16), (24, 24), (32, 32), (48, 48)])

    def test_version_command_needs_no_display(self):
        result = subprocess.run([sys.executable, str(Path(demo.__file__)), '--version'],
                                capture_output=True, text=True, timeout=10,
                                env={**os.environ, 'DISPLAY': ''})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f'{demo.APP_NAME} {demo.__version__}')


@unittest.skipUnless(demo.tk is not None and os.environ.get('RUN_GUI_TESTS') == '1',
                     'Set RUN_GUI_TESTS=1 and provide a graphical display for Tk checks.')
class BrandingGuiTests(unittest.TestCase):
    def setUp(self):
        self.browser_patch = patch('dijkstra_routing_demo.webbrowser.open', return_value=True)
        self.browser = self.browser_patch.start()
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
        with patch('dijkstra_routing_demo.messagebox.askyesnocancel', return_value=False):
            self.app.close()
        self.browser_patch.stop()
        self.assertEqual(self.errors, [])

    def test_header_displays_both_real_images_without_network_access(self):
        self.assertEqual(self.app.asset_warnings, [])
        self.assertTrue(self.app.ihn_header.cget('image'))
        self.assertTrue(self.app.ucn_header.cget('image'))
        self.assertEqual(self.app.brand_images['ihn'].width(), 48)
        self.assertEqual(self.app.brand_images['ucn'].width(), 104)
        self.browser.assert_not_called()

    def test_about_button_contains_purpose_copyright_version_and_repository(self):
        self.app.about_button.invoke()
        self.root.update()
        window = self.app.about_window
        self.assertIsNotNone(window)
        self.assertEqual(self.root.grab_current(), window)
        self.assertIn('PURPOSE', self.app.about_text.get('1.0', 'end'))
        self.assertIn('not a full OSPF', self.app.about_text.get('1.0', 'end'))
        self.assertEqual(self.app.about_repo_value.get(), demo.REPOSITORY_URL)
        labels = []
        for child in descendants(window):
            try:
                labels.append(str(child.cget('text')))
            except demo.tk.TclError:
                pass
        content = ' '.join(labels)
        self.assertIn(demo.__copyright__, content)
        self.assertIn(demo.__version__, content)
        self.assertIn('Apache License 2.0', content)
        self.browser.assert_not_called()

    def test_about_is_singleton_and_help_menu_opens_it(self):
        self.app.help_menu.invoke(0)
        first = self.app.about_window
        self.assertIs(self.app.show_about(), first)
        self.assertEqual(len([w for w in self.root.winfo_children()
                              if isinstance(w, demo.tk.Toplevel)]), 1)
        self.app.about_close_button.invoke()
        self.assertIsNone(self.app.about_window)
        self.assertIsNone(self.root.grab_current())
        second = self.app.show_about()
        self.assertIsNot(second, first)

    def test_f1_and_escape_keyboard_actions(self):
        self.root.focus_force()
        self.root.event_generate('<F1>')
        self.root.update()
        self.assertIsNotNone(self.app.about_window)
        self.app.about_window.focus_force()
        self.app.about_window.event_generate('<Escape>')
        self.root.update()
        self.assertIsNone(self.app.about_window)

    def test_open_github_uses_only_fixed_repository_url_on_click(self):
        self.app.show_about()
        self.browser.assert_not_called()
        self.app.about_repo_value.set('https://example.invalid/untrusted')
        self.app.about_open_button.invoke()
        self.browser.assert_called_once_with(demo.REPOSITORY_URL, new=2)

    def test_browser_failure_displays_a_useful_warning(self):
        self.app.show_about()
        with patch('dijkstra_routing_demo.messagebox.showwarning') as warning:
            self.browser.return_value = False
            self.assertFalse(self.app.open_repository())
            self.assertIn(demo.REPOSITORY_URL, warning.call_args.args[1])
            self.browser.side_effect = demo.webbrowser.Error('no browser')
            self.assertFalse(self.app.open_repository())
            self.assertEqual(warning.call_count, 2)

    def test_copy_link_uses_the_clipboard_without_opening_a_browser(self):
        self.app.show_about()
        self.app.about_copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), demo.REPOSITORY_URL)
        self.assertEqual(self.app.about_feedback.get(), 'Link copied')
        self.browser.assert_not_called()

    def test_clipboard_failure_does_not_crash(self):
        self.app.show_about()
        with patch.object(self.root, 'clipboard_append', side_effect=demo.tk.TclError('unavailable')):
            with patch('dijkstra_routing_demo.messagebox.showwarning') as warning:
                self.assertFalse(self.app.copy_repository())
                warning.assert_called_once()

    def test_open_close_preserves_unsaved_graph_tables_and_spf_work(self):
        self.app.build_all()
        self.app.network.move_router('A', .15, .55)
        self.app.animate_all()
        self.root.update()
        before = self.app.engine.export_data()
        iterator, queue = self.app.iterator, list(self.app.spf_queue)
        saved = self.app.saved_graph
        self.app.show_about()
        self.assertFalse(self.app.spf_auto)
        self.assertIsNone(self.app.spf_job)
        self.assertIs(self.app.iterator, iterator)
        self.assertEqual(list(self.app.spf_queue), queue)
        self.assertEqual(self.app.engine.export_data(), before)
        self.assertIs(self.app.saved_graph, saved)
        self.assertTrue(self.app.has_unsaved_graph())
        self.app.close_about()
        self.assertFalse(self.app.spf_auto)
        self.app.toggle_spf()
        self.assertTrue(self.app.spf_auto)

    def test_open_close_preserves_packet_and_routing_tables(self):
        self.app.build_all()
        self.app.new_packet()
        self.app.step_packet()
        packet = self.app.packet
        before = (list(packet.path), packet.ttl, packet.total_cost)
        self.app.show_about()
        self.assertIs(self.app.packet, packet)
        self.assertEqual((list(packet.path), packet.ttl, packet.total_cost), before)
        self.assertFalse(self.app.packet_animating)
        self.assertIsNone(self.app.frame_job)
        self.app.close_about()
        self.assertFalse(self.app.has_unsaved_graph())
        self.assertTrue(all(self.app.engine.table_status(r) == 'current' for r in self.app.network.routers))

    def test_about_respects_an_existing_editor_grab(self):
        editor = self.app.add_router_dialog()
        self.assertIsNone(self.app.show_about())
        self.assertEqual(self.root.grab_current(), editor)
        self.assertIsNone(self.app.about_window)

    def test_file_shortcuts_and_editors_are_blocked_while_about_is_open(self):
        about = self.app.show_about()
        with patch('dijkstra_routing_demo.filedialog.asksaveasfilename') as save:
            with patch('dijkstra_routing_demo.filedialog.askopenfilename') as load:
                self.assertFalse(self.app.save_graph())
                self.assertFalse(self.app.load_graph())
                self.assertIsNone(self.app.add_router_dialog())
                save.assert_not_called()
                load.assert_not_called()
        self.assertEqual(self.root.grab_current(), about)

    def test_small_layout_keeps_branding_and_about_buttons_visible(self):
        self.root.geometry('1180x740')
        self.root.update()
        for child in (self.app.ihn_header, self.app.ucn_header, self.app.about_button):
            self.assertTrue(child.winfo_ismapped())
            self.assertLessEqual(child.winfo_rootx() + child.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
        about = self.app.show_about()
        about.geometry('600x480')
        self.root.update()
        for child in (self.app.about_open_button, self.app.about_copy_button, self.app.about_close_button):
            self.assertTrue(child.winfo_ismapped())
            self.assertLessEqual(child.winfo_rooty() + child.winfo_height(), about.winfo_rooty() + about.winfo_height())
        self.assertGreater(self.app.about_text.winfo_height(), 80)

    def test_missing_or_invalid_assets_fall_back_to_text_without_crashing(self):
        self.app.close()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'ucn-logo.png').write_text('not an image')
            with patch('dijkstra_routing_demo.ASSET_DIR', Path(directory)):
                self.root = demo.tk.Tk()
                self.root.report_callback_exception = lambda *args: self.errors.append(args)
                self.app = demo.RoutingDemo(self.root)
                self.root.update()
                self.assertEqual(self.app.brand_images, {})
                self.assertEqual(len(self.app.asset_warnings), 3)
                self.assertEqual(self.app.ihn_header.cget('text'), 'IHN')
                self.assertEqual(self.app.ucn_header.cget('text'), 'UCN')
                self.app.show_about()
                self.assertIsNotNone(self.app.about_window)

    def test_assets_work_from_a_different_working_directory(self):
        self.app.close()
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.root = demo.tk.Tk()
                self.root.report_callback_exception = lambda *args: self.errors.append(args)
                self.app = demo.RoutingDemo(self.root)
                self.assertEqual(self.app.asset_warnings, [])
                self.assertTrue(self.app.ucn_header.cget('image'))
            finally:
                os.chdir(original)


if __name__ == '__main__':
    unittest.main()
