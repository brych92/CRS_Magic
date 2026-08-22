from pathlib import Path
from typing import List, Optional

from qgis.PyQt import sip
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMenu, QToolBar
from qgis.core import QgsApplication
from qgis.gui import QgisInterface

try:
    # QAction moved from QtWidgets to QtGui in Qt 6.
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction


MENU_OBJECT_NAME = "ua_spt_menu"
MENU_ANCHOR_OBJECT_NAME = "ua_spt_menu_anchor"
TOOLBAR_OBJECT_NAME = "ua_spt_panel"


def _is_ukrainian_locale() -> bool:
    try:
        return str(QgsApplication.locale()).strip().lower().startswith("uk")
    except (AttributeError, RuntimeError):
        return False


def _localized(ukrainian: str, english: str) -> str:
    return ukrainian if _is_ukrainian_locale() else english


def _menu_title() -> str:
    return _localized("Плагіни UA SPT", "UA SPT Plugins")


def _menu_tooltip() -> str:
    return _localized(
        'Меню ініціативи «Відкриті інструменти просторового '
        'планування для України»',
        'Plugin menu of the "Open Spatial Planning Tools for Ukraine" '
        "initiative",
    )


def _toolbar_title() -> str:
    return _localized("🚀Панель UA SPT", "🚀UA SPT Toolbar")


def _toolbar_tooltip() -> str:
    return _localized(
        'Панель ініціативи «Відкриті інструменти просторового '
        'планування для України»',
        'Toolbar of the "Open Spatial Planning Tools for Ukraine" initiative',
    )


class uaSPT:
    """Add plugin actions to the shared UA SPT menu and toolbar.

    ``uaSPT(iface)`` remains valid and has no UI side effects. Legacy callers
    can request the shared containers explicitly through ``getMenu(iface)``
    and ``getToolbar(iface)``.
    """

    def __init__(
        self,
        iface: QgisInterface,
        toolbar_action: Optional[QAction] = None,
        menu_actions: Optional[List[QAction]] = None,
        plugin_menu_name: Optional[str] = None,
        plugin_menu_icon: Optional[QIcon] = None,
    ):
        self.iface = iface
        self.TB_action = toolbar_action
        self.menu_actions = menu_actions
        self.plugin_menu_name = plugin_menu_name
        self.menu_icon = plugin_menu_icon
        self.SPT_toolbar = None
        self.SPT_menu = None
        self.plugin_menu = None
        self._registered_menu_action = None

        if menu_actions and len(menu_actions) > 1 and plugin_menu_name is None:
            raise ValueError(
                _localized(
                    "Помилка ініціалізації uaSPT: передано більше однієї QAction, "
                    "але не вказано plugin_menu_name.",
                    "uaSPT initialization error: more than one QAction was "
                    "supplied, but plugin_menu_name is missing.",
                )
            )
        if plugin_menu_icon is not None and not isinstance(plugin_menu_icon, QIcon):
            raise TypeError(
                _localized(
                    "Помилка ініціалізації uaSPT: plugin_menu_icon має бути QIcon.",
                    "uaSPT initialization error: plugin_menu_icon must be a QIcon.",
                )
            )

        if toolbar_action is None and not menu_actions:
            return

        self.SPT_toolbar = self.getToolbar(self.iface)
        self._registered_menu_action = self._createMenuRegistrationAction()

        if self._registered_menu_action is not None:
            self.iface.addPluginToMenu(
                _menu_title(),
                self._registered_menu_action,
            )
            self.SPT_menu = self._menuContainingAction(
                self.iface.pluginMenu(),
                self._registered_menu_action,
            )
            if self.SPT_menu is not None:
                self._configureMenu(self.SPT_menu)

        if self.TB_action is not None:
            self.SPT_toolbar.addAction(self.TB_action)

    def tr(self, message):
        return self.iface.tr(message)

    @staticmethod
    def _loadInitiativeIcon(filename: str = "SPT_icon.png") -> Optional[QIcon]:
        path = Path(__file__).resolve().parent / filename
        if not path.exists():
            return None

        icon = QIcon(str(path))
        return None if icon.isNull() else icon

    @staticmethod
    def _menuContainingAction(root: QMenu, action: QAction) -> Optional[QMenu]:
        for root_action in root.actions():
            menu = root_action.menu()
            if menu is not None and action in menu.actions():
                return menu
        return None

    @staticmethod
    def _configureMenu(menu: QMenu) -> None:
        menu.setObjectName(MENU_OBJECT_NAME)
        menu.setTitle(_menu_title())
        menu.setToolTip(_menu_tooltip())
        icon = uaSPT._loadInitiativeIcon()
        if icon is not None:
            menu.setIcon(icon)

    def _createMenuRegistrationAction(self) -> Optional[QAction]:
        if not self.menu_actions:
            return self.TB_action

        if len(self.menu_actions) == 1:
            return self.menu_actions[0]

        self.plugin_menu = QMenu(self.iface.mainWindow())
        self.plugin_menu.setTitle(self.plugin_menu_name)
        if self.menu_icon is not None:
            self.plugin_menu.setIcon(self.menu_icon)
        for action in self.menu_actions:
            self.plugin_menu.addAction(action)
        return self.plugin_menu.menuAction()

    @staticmethod
    def getMenu(iface) -> QMenu:
        """Return the shared menu using QGIS-native plugin registration."""
        root: QMenu = iface.pluginMenu()
        for root_action in root.actions():
            menu = root_action.menu()
            if menu and menu.objectName() == MENU_OBJECT_NAME:
                uaSPT._configureMenu(menu)
                return menu

        # A legacy caller requests an empty QMenu before it has an action to
        # register. A hidden QAction lets QGIS create and position the group.
        anchor = QAction(root)
        anchor.setObjectName(MENU_ANCHOR_OBJECT_NAME)
        anchor.setVisible(False)
        iface.addPluginToMenu(_menu_title(), anchor)

        menu = uaSPT._menuContainingAction(root, anchor)
        if menu is None:
            raise RuntimeError(
                _localized(
                    "QGIS не створив меню плагінів UA SPT.",
                    "QGIS did not create the UA SPT plugin menu.",
                )
            )
        uaSPT._configureMenu(menu)
        return menu

    def _getMenu(self) -> QMenu:
        return self.getMenu(self.iface)

    def _removeFromMenu(self) -> None:
        action = self._registered_menu_action
        if action is None or sip.isdeleted(action):
            return

        try:
            self.iface.removePluginMenu(_menu_title(), action)
        except RuntimeError:
            pass

        if self.plugin_menu is not None and not sip.isdeleted(self.plugin_menu):
            self.plugin_menu.deleteLater()

        self._registered_menu_action = None
        self.plugin_menu = None
        self.SPT_menu = None

    @staticmethod
    def getToolbar(iface) -> QToolBar:
        """Return the shared UA SPT toolbar (legacy public API)."""
        toolbar: QToolBar = iface.mainWindow().findChild(
            QToolBar,
            TOOLBAR_OBJECT_NAME,
        )
        if not toolbar:
            toolbar = iface.addToolBar(_toolbar_title())
            toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        else:
            toolbar.setWindowTitle(_toolbar_title())
        toolbar.setToolTip(_toolbar_tooltip())
        return toolbar

    def _getToolbar(self) -> QToolBar:
        return self.getToolbar(self.iface)

    def _removeFromToolbar(self) -> None:
        if self.TB_action is None:
            return

        toolbar = self.iface.mainWindow().findChild(
            QToolBar,
            TOOLBAR_OBJECT_NAME,
        )
        if toolbar is None or sip.isdeleted(toolbar):
            return

        if self.TB_action in toolbar.actions():
            toolbar.removeAction(self.TB_action)

        if not [action for action in toolbar.actions() if not action.isSeparator()]:
            self.iface.mainWindow().removeToolBar(toolbar)
            toolbar.setObjectName(f"{TOOLBAR_OBJECT_NAME}__to_delete")
            toolbar.deleteLater()

    def unload(self):
        if self.TB_action is None and not self.menu_actions:
            return
        self._removeFromMenu()
        self._removeFromToolbar()
