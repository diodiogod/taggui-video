"""Context switch manager.

Handles swapping the right-side panels (Image Tags, All Tags) and the
main viewer between the primary and secondary browser contexts.

The primary pipeline is never permanently modified — we swap model
references, reconnect ~3 tag-write signals, and swap the viewer's
proxy reference. Everything is fully reversible.
"""

import traceback as _traceback

from PySide6.QtCore import QModelIndex


class ContextSwitchManager:
    """Manages swapping panels between primary and secondary contexts.

    Context dict keys:
        'name': 'primary' | 'secondary'
        'proxy_index': QModelIndex  (from the emitting browser's selection)
        'image_list_model': ImageListModel
        'proxy_image_list_model': ProxyImageListModel
        'tag_counter_model': TagCounterModel
        'image_list': ImageList dock  (the source panel)
    """

    def __init__(self, main_window):
        self.main_window = main_window
        self._active_context_name: str = 'primary'
        self._connected_image_list_model = None
        self._connected_tag_counter_model = None
        # Track which proxy is currently in the viewer so we can properly
        # disconnect reset signals before swapping.
        self._viewer_proxy = None

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry points
    # ─────────────────────────────────────────────────────────────────────────

    def switch_to_context(self, ctx: dict):
        try:
            self._do_switch(ctx)
        except Exception as exc:
            print(f'[ContextSwitchManager] switch error: {exc}')
            _traceback.print_exc()

    def restore_primary(self):
        mw = self.main_window
        ctx = {
            'name': 'primary',
            'proxy_index': mw.image_list_selection_model.currentIndex(),
            'image_list_model': mw.image_list_model,
            'proxy_image_list_model': mw.proxy_image_list_model,
            'tag_counter_model': mw.tag_counter_model,
            'image_list': mw.image_list,
        }
        self.switch_to_context(ctx)

    # ─────────────────────────────────────────────────────────────────────────
    # Core switch
    # ─────────────────────────────────────────────────────────────────────────

    def _do_switch(self, ctx: dict):
        mw = self.main_window
        ctx_name: str = str(ctx.get('name') or 'primary')
        proxy_index: QModelIndex = ctx.get('proxy_index') or QModelIndex()
        new_image_model = ctx['image_list_model']
        new_proxy = ctx['proxy_image_list_model']
        new_tag_counter = ctx['tag_counter_model']

        same_context = (
            self._active_context_name == ctx_name
            and self._connected_image_list_model is new_image_model
        )

        # ── 1. Swap viewer proxy + load image ───────────────────────────────
        try:
            target_viewer = mw.get_selection_target_viewer()
            self._swap_viewer_proxy(target_viewer, new_proxy)
            if proxy_index.isValid():
                # proxy_index is from new_proxy (SecondaryBrowser emits current
                # from its own selection model, which owns new_proxy).
                target_viewer.load_image(proxy_index)
        except Exception as exc:
            print(f'[ContextSwitchManager] viewer error: {exc}')
            _traceback.print_exc()

        if same_context:
            return  # Already pointing to this context; viewer already updated.

        old_image_model = self._connected_image_list_model
        old_tag_counter = self._connected_tag_counter_model

        # ── 2. Disconnect old tag-write signals ─────────────────────────────
        self._disconnect_tag_signals(old_image_model, old_tag_counter)

        # ── 3. Swap ImageTagsEditor proxy + load tags ────────────────────────
        try:
            mw.image_tags_editor.proxy_image_list_model = new_proxy
            if proxy_index.isValid():
                mw.image_tags_editor.load_image_tags(proxy_index)
        except Exception as exc:
            print(f'[ContextSwitchManager] tags error: {exc}')

        # ── 4. Swap All Tags panel ───────────────────────────────────────────
        try:
            ate = mw.all_tags_editor
            ate.tag_counter_model = new_tag_counter
            ate.proxy_tag_counter_model.setSourceModel(new_tag_counter)
            ate.sort_tags()
            ate.update_tag_count_label()
            new_tag_counter.all_tags_list = ate.all_tags_list
        except Exception as exc:
            print(f'[ContextSwitchManager] all_tags error: {exc}')

        # ── 5. Reconnect new tag-write signals ───────────────────────────────
        self._connect_tag_signals(new_image_model, new_tag_counter)

        # ── 6. Visual indicators ─────────────────────────────────────────────
        self._update_visual_indicators(ctx_name)

        # ── 7. Bookkeeping ───────────────────────────────────────────────────
        self._active_context_name = ctx_name
        self._connected_image_list_model = new_image_model
        self._connected_tag_counter_model = new_tag_counter

        print(f'[ContextSwitchManager] switched → {ctx_name}')

    # ─────────────────────────────────────────────────────────────────────────
    # Viewer proxy swap
    # ─────────────────────────────────────────────────────────────────────────

    def _swap_viewer_proxy(self, viewer, new_proxy):
        """Replace viewer.proxy_image_list_model with new_proxy.

        Disconnects the old model's reset signals, swaps the attribute,
        reconnects with the new model.  Safe to call even when old == new.
        """
        old_proxy = getattr(viewer, 'proxy_image_list_model', None)
        if old_proxy is new_proxy:
            return  # Nothing to do

        # Disconnect old reset guards
        if old_proxy is not None:
            try:
                old_proxy.modelAboutToBeReset.disconnect(viewer._on_proxy_model_about_to_reset)
            except Exception:
                pass
            try:
                old_proxy.modelReset.disconnect(viewer._on_proxy_model_reset)
            except Exception:
                pass

        # Swap
        viewer.proxy_image_list_model = new_proxy
        self._viewer_proxy = new_proxy

        # Reconnect reset guards with new model
        try:
            new_proxy.modelAboutToBeReset.connect(viewer._on_proxy_model_about_to_reset)
            new_proxy.modelReset.connect(viewer._on_proxy_model_reset)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Tag-write signal management
    # ─────────────────────────────────────────────────────────────────────────

    def _disconnect_tag_signals(self, old_model, old_tag_counter):
        if old_model is None:
            return
        mw = self.main_window
        _safe_disconnect(
            mw.image_tags_editor.tag_input_box.tags_addition_requested,
            old_model.add_tags,
        )
        _safe_disconnect(
            mw.all_tags_editor.all_tags_list.tags_deletion_requested,
            old_model.delete_tags,
        )
        if old_tag_counter is not None:
            _safe_disconnect(
                old_tag_counter.tags_renaming_requested,
                old_model.rename_tags,
            )

    def _connect_tag_signals(self, new_model, new_tag_counter):
        if new_model is None:
            return
        mw = self.main_window
        try:
            mw.image_tags_editor.tag_input_box.tags_addition_requested.connect(
                new_model.add_tags)
        except Exception:
            pass
        try:
            mw.all_tags_editor.all_tags_list.tags_deletion_requested.connect(
                new_model.delete_tags)
        except Exception:
            pass
        if new_tag_counter is not None:
            try:
                new_tag_counter.tags_renaming_requested.connect(new_model.rename_tags)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Visual indicators
    # ─────────────────────────────────────────────────────────────────────────

    def _update_visual_indicators(self, context_name: str):
        is_secondary = (context_name == 'secondary')

        # Secondary dock title bullet
        sb = getattr(self.main_window, '_secondary_browser', None)
        if sb is not None:
            try:
                sb.set_active_context(is_secondary)
            except Exception:
                pass

        # Primary image list title
        primary = getattr(self.main_window, 'image_list', None)
        if primary is not None:
            try:
                primary.setWindowTitle('Images  (inactive)' if is_secondary else 'Images')
            except Exception:
                pass

        # Image Tags editor title
        ite = getattr(self.main_window, 'image_tags_editor', None)
        if ite is not None:
            try:
                ite.setWindowTitle(
                    'Image Tags  (Browser 2)' if is_secondary else 'Image Tags')
            except Exception:
                pass

        # All Tags editor title
        ate = getattr(self.main_window, 'all_tags_editor', None)
        if ate is not None:
            try:
                ate.setWindowTitle(
                    'All Tags  (Browser 2)' if is_secondary else 'All Tags')
            except Exception:
                pass

        # Gray out auto-captioner start button when secondary is active
        ac = getattr(self.main_window, 'auto_captioner', None)
        if ac is not None:
            try:
                btn = getattr(ac, 'start_cancel_button', None)
                if btn is not None:
                    if is_secondary:
                        btn.setDisabled(True)
                        btn.setToolTip(
                            'Switch back to Browser 1 to use auto-captioner')
                    else:
                        has_dir = bool(getattr(self.main_window, 'directory_path', None))
                        btn.setDisabled(not has_dir)
                        btn.setToolTip('')
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def active_context(self) -> str:
        return self._active_context_name


def _safe_disconnect(signal, slot):
    """Disconnect signal→slot without raising if not connected."""
    try:
        signal.disconnect(slot)
    except Exception:
        pass
