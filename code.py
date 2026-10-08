import json
import os

from qgis.PyQt.QtGui import QCursor, QDesktopServices, QIcon, QPixmap
from qgis.PyQt.QtWidgets import QAction, QApplication, QMenu
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsGeometry,
    QgsMapLayerType,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsVectorLayerFeatureSource,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt, QTimer, QSettings, QUrl
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

from .find_crs import clear_all_crs_filter_cache, findCrs
from .plugin_window import CRSResultsDialog
from .settings_window import (
    CRSSetSettingsDialog,
    crs_sets_bundle_from_json_data,
    crs_sets_to_json_data,
)
from .ua_SPT import uaSPT


ALL_CRS_SET_KEY = '__all__'
DEFAULT_ACTIVE_CRS_SET = 'Ukraine - UCS/CS63'
ACTIVE_CRS_SET_SETTINGS_KEY = 'CRS_Magic/active_crs_set'
FAST_MODE_SETTINGS_KEY = 'CRS_Magic/fast_mode'
GROUP_SEARCH_SETTINGS_KEY = 'CRS_Magic/group_search'
DISABLE_FALLBACK_HANDLER_SETTINGS_KEY = 'CRS_Magic/disable_fallback_handler'
ALLOW_FALLBACK_SETTINGS_KEY = 'CRS_Magic/allow_fallback'
ALLOW_BALLPARK_SETTINGS_KEY = 'CRS_Magic/allow_ballpark'
FILTER_BY_CRS_BOUNDS_SETTINGS_KEY = 'CRS_Magic/filter_by_crs_bounds'
INITIAL_CRS_SETS_VERSION = 1
CRS_SETS_LIBRARY_DIRECTORY = 'CRS_Magic_finder'
CRS_SETS_LIBRARY_FILE = 'crs_sets.json'
TRANSFORM_MESSAGE_LOG_TAG = 'CRS Magic finder / трансформації'


class CRS_Magic:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.folder_path=os.path.expanduser('~')
        self.activated=False
        
        self.pointTool = QgsMapToolEmitPoint(self.iface.mapCanvas())
        cursor_pixmap=QPixmap(os.path.join(self.plugin_dir,"cursor.png")).scaledToHeight(32,Qt.SmoothTransformation)
        cursor=QCursor(cursor_pixmap)
        self.pointTool.setCursor(cursor)
        self.pointTool.canvasClicked.connect(self.get_CRS_dict)
        self.pointTool.deactivated.connect(self.tool_chaged)
        
        self.layers=[]
        self.selected_layers=[]
        self.results_dialog=None
        self.action_reference = None
        self.settings = QSettings()
        (
            self.crs_sets,
            self.crs_set_metadata,
            self.initial_crs_sets_version,
        ) = self.load_crs_sets()
        self.install_initial_crs_sets()
        self.active_crs_set = self.load_active_crs_set()
        self.fast_mode = self.load_bool_setting(FAST_MODE_SETTINGS_KEY, False)
        self.group_search = self.load_bool_setting(GROUP_SEARCH_SETTINGS_KEY, False)
        self.disable_fallback_handler = self.load_bool_setting(
            DISABLE_FALLBACK_HANDLER_SETTINGS_KEY,
            True,
        )
        self.allow_fallback = self.load_bool_setting(ALLOW_FALLBACK_SETTINGS_KEY, True)
        self.allow_ballpark = self.load_bool_setting(ALLOW_BALLPARK_SETTINGS_KEY, False)
        self.filter_by_crs_bounds = self.load_bool_setting(
            FILTER_BY_CRS_BOUNDS_SETTINGS_KEY,
            False,
        )
        self.crs_menu = None
        self.plugin_help_menu = None
        self.plugin_help_action = None
        self.SPT = None
        self.transform_message_interceptor_connected = False
        self.transform_message_interceptor_active = False
        self.transform_message_interceptor_generation = 0
        
    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir,"icon.png"))
        tooltip = self.main_action_tooltip()
        self.crs_menu = QMenu(self.iface.mainWindow())
        
        action = QAction(icon, 'CRS Magic finder', self.iface.mainWindow())
        action.setToolTip(tooltip)
        action.triggered.connect(self.Run)
        action.setEnabled(True)
        action.setCheckable(True)
        action.setMenu(self.crs_menu)
        self.SPT = uaSPT(self.iface, action, [action])
        self.actions.append(action)
        self.action_reference=action
        self.register_plugin_help_action(icon)
        self.rebuild_crs_menu()
        
    def unload(self):
        self.disconnect_transform_message_interceptor()
        if self.plugin_help_menu is not None and self.plugin_help_action is not None:
            self.plugin_help_menu.removeAction(self.plugin_help_action)
        if self.plugin_help_action is not None:
            self.plugin_help_action.deleteLater()
        self.plugin_help_menu = None
        self.plugin_help_action = None
        if self.SPT is not None:
            self.SPT.unload()
        self.SPT = None

    def register_plugin_help_action(self, icon):
        self.plugin_help_menu = self.iface.pluginHelpMenu()
        if self.plugin_help_menu is None:
            return

        self.plugin_help_action = QAction(
            icon,
            'CRS Magic finder',
            self.iface.mainWindow(),
        )
        self.plugin_help_action.setToolTip(
            'Відкрити інструкцію з використання плагіна'
        )
        self.plugin_help_action.triggered.connect(self.open_help)
        self.plugin_help_menu.addAction(self.plugin_help_action)

    def load_crs_sets(self):
        file_path = self.crs_sets_library_path()
        if not os.path.isfile(file_path):
            return {}, {}, 0
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as library_file:
                data = json.load(library_file)
            crs_sets, crs_set_metadata, _ = crs_sets_bundle_from_json_data(data)
            initial_version = int(data.get('initial_crs_sets_version', 0))
        except Exception as error:
            QgsMessageLog.logMessage(
                f'Не вдалося прочитати {file_path}: {error}',
                'CRS Magic finder',
                Qgis.MessageLevel.Warning,
            )
            return {}, {}, 0
        return crs_sets, crs_set_metadata, initial_version

    def crs_sets_library_path(self):
        return os.path.join(
            QgsApplication.qgisSettingsDirPath(),
            CRS_SETS_LIBRARY_DIRECTORY,
            CRS_SETS_LIBRARY_FILE,
        )

    def save_crs_sets(self):
        file_path = self.crs_sets_library_path()
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        data = crs_sets_to_json_data(self.crs_sets, self.crs_set_metadata)
        data['initial_crs_sets_version'] = self.initial_crs_sets_version
        temporary_path = f'{file_path}.tmp'
        with open(temporary_path, 'w', encoding='utf-8') as library_file:
            json.dump(data, library_file, ensure_ascii=False, indent=2)
            library_file.write('\n')
        os.replace(temporary_path, file_path)

    def install_initial_crs_sets(self):
        if self.initial_crs_sets_version >= INITIAL_CRS_SETS_VERSION:
            return

        initial_directory = os.path.realpath(
            os.path.join(self.plugin_dir, 'initial_crs_sets')
        )
        plugin_directory = os.path.realpath(self.plugin_dir)
        try:
            is_inside_plugin = (
                os.path.commonpath([initial_directory, plugin_directory])
                == plugin_directory
            )
        except ValueError:
            is_inside_plugin = False
        if not is_inside_plugin or not os.path.isdir(initial_directory):
            return

        errors = []
        for file_name in sorted(os.listdir(initial_directory)):
            if not file_name.lower().endswith('.json'):
                continue
            file_path = os.path.join(initial_directory, file_name)
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as source_file:
                    data = json.load(source_file)
                initial_sets, initial_metadata, _ = (
                    crs_sets_bundle_from_json_data(data)
                )
            except Exception as error:
                errors.append(f'{file_name}: {error}')
                continue

            for name, codes in initial_sets.items():
                if name in self.crs_sets:
                    continue
                self.crs_sets[name] = codes
                if name in initial_metadata:
                    self.crs_set_metadata[name] = initial_metadata[name]

        self.initial_crs_sets_version = INITIAL_CRS_SETS_VERSION
        try:
            self.save_crs_sets()
        except OSError as error:
            QgsMessageLog.logMessage(
                f'Не вдалося зберегти початкові набори СК: {error}',
                'CRS Magic finder',
                Qgis.MessageLevel.Warning,
            )

        if errors:
            QgsMessageLog.logMessage(
                '\n'.join(errors),
                'CRS Magic finder',
                Qgis.MessageLevel.Warning,
            )

    def load_active_crs_set(self):
        if not self.settings.contains(ACTIVE_CRS_SET_SETTINGS_KEY):
            active_set = (
                DEFAULT_ACTIVE_CRS_SET
                if DEFAULT_ACTIVE_CRS_SET in self.crs_sets
                else ALL_CRS_SET_KEY
            )
            self.settings.setValue(ACTIVE_CRS_SET_SETTINGS_KEY, active_set)
            self.settings.sync()
            return active_set

        active_set = self.settings.value(ACTIVE_CRS_SET_SETTINGS_KEY, ALL_CRS_SET_KEY)
        active_set = str(active_set or ALL_CRS_SET_KEY)
        if active_set != ALL_CRS_SET_KEY and active_set not in self.crs_sets:
            return ALL_CRS_SET_KEY
        return active_set

    def save_active_crs_set(self):
        self.settings.setValue(ACTIVE_CRS_SET_SETTINGS_KEY, self.active_crs_set)

    def load_bool_setting(self, key, default=False):
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    def set_bool_setting(self, attribute, key, enabled):
        setattr(self, attribute, bool(enabled))
        self.settings.setValue(key, bool(enabled))
        self.settings.sync()
        if self.action_reference:
            self.action_reference.setToolTip(self.main_action_tooltip())

    def active_crs_set_label(self):
        if self.active_crs_set == ALL_CRS_SET_KEY:
            return 'Усі СК'
        codes = self.crs_sets.get(self.active_crs_set, [])
        return f'{self.active_crs_set} ({len(codes)} СК)'

    def active_crs_codes(self):
        if self.active_crs_set == ALL_CRS_SET_KEY:
            return None

        codes = self.crs_sets.get(self.active_crs_set)
        if not codes:
            self.active_crs_set = ALL_CRS_SET_KEY
            self.save_active_crs_set()
            self.rebuild_crs_menu()
            return None

        return codes

    def main_action_tooltip(self):
        search_mode = 'груповий' if self.group_search else 'окремий для кожного шару'
        crs_mode = 'швидкий' if self.fast_mode else 'через PROJ-рядок'
        return (
            "<b>CRS Magic finder</b> ・*.ﾟ☆\n"
            f"Підібрати СК для вибраних векторних і растрових шарів\n"
            f"Набір СК: {self.active_crs_set_label()}\n"
            f"Пошук: {search_mode}\nРежим СК: {crs_mode}\n"
            'Область застосування СК: '
            f"{'враховується' if self.filter_by_crs_bounds else 'не враховується'}"
        )

    def rebuild_crs_menu(self):
        if not self.crs_menu:
            return

        self.crs_menu.clear()
        self.crs_menu.setToolTipsVisible(True)

        if self.action_reference is not None:
            main_action = self.crs_menu.addAction(
                self.action_reference.icon(),
                self.action_reference.text(),
            )
            main_action.setToolTip(self.main_action_tooltip())
            main_action.triggered.connect(self.Run)
            self.crs_menu.addSeparator()

        all_action = self.crs_menu.addAction('Усі СК')
        all_action.setCheckable(True)
        all_action.setChecked(self.active_crs_set == ALL_CRS_SET_KEY)
        all_action.setToolTip(
            'Перевірити всі земні горизонтальні 2D-системи координат '
            'із бази QGIS. Застарілі СК не відсіюються.'
        )
        all_action.triggered.connect(lambda checked=False: self.set_active_crs_set(ALL_CRS_SET_KEY))

        if self.crs_sets:
            self.crs_menu.addSeparator()
            for set_name in sorted(self.crs_sets.keys()):
                codes = self.crs_sets.get(set_name, [])
                action = self.crs_menu.addAction(f'{set_name} ({len(codes)} СК)')
                action.setCheckable(True)
                action.setChecked(self.active_crs_set == set_name)
                description = str(
                    self.crs_set_metadata.get(set_name, {}).get(
                        'description',
                        '',
                    )
                ).strip()
                action.setToolTip(
                    description
                    or f'Перевірити {len(codes)} СК із набору «{set_name}».'
                )
                action.triggered.connect(lambda checked=False, name=set_name: self.set_active_crs_set(name))

        self.crs_menu.addSeparator()
        search_menu = self.crs_menu.addMenu('Режими пошуку')
        search_menu.setToolTipsVisible(True)
        search_menu.menuAction().setToolTip(
            'Налаштувати спосіб підготовки та перевірки можливих СК.'
        )

        fast_mode_action = search_menu.addAction(
            'Швидкий режим (без PROJ-рядків)'
        )
        fast_mode_action.setCheckable(True)
        fast_mode_action.setChecked(self.fast_mode)
        fast_mode_action.setToolTip(
            'Використовує визначення СК безпосередньо з бази QGIS. '
            'Може пришвидшити підготовку, але на старих версіях QGIS '
            'інколи дає некоректні результати.'
        )
        fast_mode_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'fast_mode',
                FAST_MODE_SETTINGS_KEY,
                enabled,
            )
        )

        group_search_action = search_menu.addAction('Груповий підбір для кількох шарів')
        group_search_action.setCheckable(True)
        group_search_action.setChecked(self.group_search)
        group_search_action.setToolTip(
            'Послідовно групувати шари, екстенти об’єктів яких перетинаються '
            'з найбільшим екстентом серед ще не згрупованих шарів.'
        )
        group_search_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'group_search',
                GROUP_SEARCH_SETTINGS_KEY,
                enabled,
            )
        )

        bounds_filter_action = search_menu.addAction(
            'Фільтрувати за областю застосування СК'
        )
        bounds_filter_action.setCheckable(True)
        bounds_filter_action.setChecked(self.filter_by_crs_bounds)
        bounds_filter_action.setToolTip(
            'Залишати лише результати, у яких трансформований центр даних '
            'лежить в офіційній області застосування відповідної СК. '
            'СК без визначеної області не відсіюються.'
        )
        bounds_filter_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'filter_by_crs_bounds',
                FILTER_BY_CRS_BOUNDS_SETTINGS_KEY,
                enabled,
            )
        )

        fallback_menu = self.crs_menu.addMenu('Запасні й приблизні перетворення')
        fallback_menu.setToolTipsVisible(True)
        fallback_menu.menuAction().setToolTip(
            'Керувати запасними та приблизними операціями QGIS/PROJ.'
        )

        disable_handler_action = fallback_menu.addAction(
            'Виявляти запасні перетворення (Fallback)'
        )
        disable_handler_action.setCheckable(True)
        disable_handler_action.setChecked(self.disable_fallback_handler)
        disable_handler_action.setToolTip(
            'Вимикає стандартний обробник QGIS, щоб плагін міг виявляти '
            'й позначати запасні операції. Самі запасні перетворення цей параметр не забороняє.'
        )
        disable_handler_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'disable_fallback_handler',
                DISABLE_FALLBACK_HANDLER_SETTINGS_KEY,
                enabled,
            )
        )

        allow_fallback_action = fallback_menu.addAction('Дозволяти запасні перетворення (Fallback)')
        allow_fallback_action.setCheckable(True)
        allow_fallback_action.setChecked(self.allow_fallback)
        allow_fallback_action.setToolTip(
            'Дозволяє PROJ використати запасну операцію, якщо рекомендована недоступна. '
            'Результат може бути менш точним.'
        )
        allow_fallback_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'allow_fallback',
                ALLOW_FALLBACK_SETTINGS_KEY,
                enabled,
            )
        )

        allow_ballpark_action = fallback_menu.addAction('Дозволяти приблизні перетворення (Ballpark)')
        allow_ballpark_action.setCheckable(True)
        allow_ballpark_action.setChecked(self.allow_ballpark)
        allow_ballpark_action.setToolTip(
            'Дозволяє приблизні перетворення без гарантованої геодезичної точності. '
            'Має пріоритет над забороною запасних перетворень.'
        )
        allow_ballpark_action.toggled.connect(
            lambda enabled: self.set_bool_setting(
                'allow_ballpark',
                ALLOW_BALLPARK_SETTINGS_KEY,
                enabled,
            )
        )

        self.crs_menu.addSeparator()
        settings_action = self.crs_menu.addAction('Налаштування…')
        settings_action.setToolTip(
            'Відкрити всі параметри пошуку та редактор наборів СК.'
        )
        settings_action.triggered.connect(self.open_crs_sets_settings)

        self.crs_menu.addSeparator()
        help_action = self.crs_menu.addAction('Довідка')
        help_action.setToolTip('Відкрити інструкцію з використання плагіна')
        help_action.triggered.connect(self.open_help)

        if self.action_reference:
            self.action_reference.setToolTip(self.main_action_tooltip())

    def reset_crs_filter_cache(self):
        active_task = None
        results_dialog = getattr(self, 'results_dialog', None)
        if results_dialog is not None:
            active_task = getattr(results_dialog, 'task', None)
        if active_task is not None:
            return (
                False,
                'Дочекайтеся завершення пошуку або скасуйте його перед '
                'скиданням кешу шейдерів.',
            )

        memory_entries, removed_files, errors = clear_all_crs_filter_cache()
        if errors:
            QgsMessageLog.logMessage(
                'Не вдалося повністю скинути кеш шейдерів: '
                + '; '.join(errors),
                'CRS Magic finder',
                Qgis.MessageLevel.Warning,
                False,
            )
            return (
                False,
                'Кеш шейдерів скинуто частково. Подробиці записано в журнал.',
            )

        QgsMessageLog.logMessage(
            'Кеш шейдерів скинуто: '
            f'записів у пам’яті – {memory_entries}, '
            f'файлів у профілі QGIS – {removed_files}.',
            'CRS Magic finder',
            Qgis.MessageLevel.Info,
            False,
        )
        return (
            True,
            'Кеш шейдерів скинуто. Наступний пошук «Усі СК» '
            'підготує його заново.',
        )

    def open_help(self):
        help_path = os.path.join(self.plugin_dir, 'help', 'index.html')
        if not os.path.isfile(help_path):
            self.iface.messageBar().pushMessage(
                '[CRS Magic finder] Файл довідки не знайдено.',
                Qgis.MessageLevel.Warning,
                5,
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(help_path))

    def set_active_crs_set(self, set_name):
        if set_name != ALL_CRS_SET_KEY and set_name not in self.crs_sets:
            set_name = ALL_CRS_SET_KEY

        self.active_crs_set = set_name
        self.save_active_crs_set()
        self.rebuild_crs_menu()

    def open_crs_sets_settings(self):
        dialog = CRSSetSettingsDialog(
            self.crs_sets,
            parent=self.iface.mainWindow(),
            fast_mode=self.fast_mode,
            group_search=self.group_search,
            disable_fallback_handler=self.disable_fallback_handler,
            allow_fallback=self.allow_fallback,
            allow_ballpark=self.allow_ballpark,
            filter_by_crs_bounds=self.filter_by_crs_bounds,
            source_map_canvas=self.iface.mapCanvas(),
            crs_set_metadata=self.crs_set_metadata,
            reset_cache_callback=self.reset_crs_filter_cache,
        )
        icon = QIcon(os.path.join(self.plugin_dir, "icon.png"))
        dialog.setWindowIcon(icon)

        if not dialog.exec_():
            return

        self.crs_sets = dialog.result_sets()
        self.crs_set_metadata = dialog.result_metadata()
        self.save_crs_sets()
        self.set_bool_setting(
            'fast_mode',
            FAST_MODE_SETTINGS_KEY,
            dialog.fast_mode(),
        )
        self.set_bool_setting(
            'group_search',
            GROUP_SEARCH_SETTINGS_KEY,
            dialog.group_search(),
        )
        self.set_bool_setting(
            'disable_fallback_handler',
            DISABLE_FALLBACK_HANDLER_SETTINGS_KEY,
            dialog.disable_fallback_handler(),
        )
        self.set_bool_setting(
            'allow_fallback',
            ALLOW_FALLBACK_SETTINGS_KEY,
            dialog.allow_fallback(),
        )
        self.set_bool_setting(
            'allow_ballpark',
            ALLOW_BALLPARK_SETTINGS_KEY,
            dialog.allow_ballpark(),
        )
        self.set_bool_setting(
            'filter_by_crs_bounds',
            FILTER_BY_CRS_BOUNDS_SETTINGS_KEY,
            dialog.filter_by_crs_bounds(),
        )

        if self.active_crs_set != ALL_CRS_SET_KEY and self.active_crs_set not in self.crs_sets:
            self.active_crs_set = ALL_CRS_SET_KEY
            self.save_active_crs_set()

        self.rebuild_crs_menu()
    
    def clearMBar(self):        
        mbar=self.iface.messageBar()
        for message in mbar.items():
            if message.text().startswith("[CRS Magic finder]"):
                message.dismiss()

    def message_bar_item_text(self, message):
        parts = []
        for method_name in ('title', 'text'):
            method = getattr(message, method_name, None)
            if not callable(method):
                continue
            try:
                value = str(method() or '').strip()
            except (AttributeError, RuntimeError):
                continue
            if value and value not in parts:
                parts.append(value)
        return ' '.join(parts)

    def is_preferred_transform_message(self, message):
        text = self.message_bar_item_text(message)
        if not text:
            return False
        lower_text = text.casefold()
        preferred_marker = (
            'переваж' in lower_text
            or 'preferred' in lower_text
        )
        transform_marker = (
            'перетвор' in lower_text
            or 'transform' in lower_text
        )
        return preferred_marker and transform_marker

    def connect_transform_message_interceptor(self):
        if getattr(self, 'transform_message_interceptor_connected', False):
            return
        try:
            self.iface.messageBar().widgetAdded.connect(
                self.on_message_bar_widget_added
            )
        except (AttributeError, RuntimeError):
            return
        self.transform_message_interceptor_connected = True

    def disconnect_transform_message_interceptor(self):
        self.stop_transform_message_interception()
        if not getattr(self, 'transform_message_interceptor_connected', False):
            return
        try:
            self.iface.messageBar().widgetAdded.disconnect(
                self.on_message_bar_widget_added
            )
        except (AttributeError, RuntimeError, TypeError):
            pass
        self.transform_message_interceptor_connected = False

    def start_transform_message_interception(self):
        self.connect_transform_message_interceptor()
        self.transform_message_interceptor_generation = (
            getattr(self, 'transform_message_interceptor_generation', 0) + 1
        )
        self.transform_message_interceptor_active = True

    def stop_transform_message_interception(self, expected_generation=None):
        if (
            expected_generation is not None
            and expected_generation
            != getattr(self, 'transform_message_interceptor_generation', 0)
        ):
            return
        self.transform_message_interceptor_active = False

    def schedule_transform_message_interception_stop(self):
        generation = getattr(
            self,
            'transform_message_interceptor_generation',
            0,
        )
        QTimer.singleShot(
            250,
            lambda: self.stop_transform_message_interception(generation),
        )

    def on_message_bar_widget_added(self, widget):
        if not getattr(self, 'transform_message_interceptor_active', False):
            return
        generation = getattr(
            self,
            'transform_message_interceptor_generation',
            0,
        )
        QTimer.singleShot(
            0,
            lambda: self.drain_preferred_transform_messages(generation),
        )

    def drain_preferred_transform_messages(self, expected_generation):
        if not getattr(self, 'transform_message_interceptor_active', False):
            return
        if expected_generation != getattr(
            self,
            'transform_message_interceptor_generation',
            0,
        ):
            return
        try:
            messages = list(self.iface.messageBar().items())
        except (AttributeError, RuntimeError):
            return
        for message in messages:
            if not self.is_preferred_transform_message(message):
                continue
            text = self.message_bar_item_text(message)
            QgsMessageLog.logMessage(
                text,
                TRANSFORM_MESSAGE_LOG_TAG,
                Qgis.MessageLevel.Warning,
                False,
            )
            self.dismiss_intercepted_message(message)

    def dismiss_intercepted_message(self, message):
        try:
            if message in self.iface.messageBar().items():
                message.dismiss()
        except (AttributeError, RuntimeError):
            pass

    def configure_transform_fallback(self, transformation):
        transformation.disableFallbackOperationHandler(self.disable_fallback_handler)
        transformation.setAllowFallbackTransforms(self.allow_fallback)
        transformation.setBallparkTransformsAreAppropriate(self.allow_ballpark)
    
    
    def get_CRS_dict(self,click_point):
        geographic_warnings = []

        def show_geographic_warning(message):
            if message not in geographic_warnings:
                geographic_warnings.append(message)
            message_bar.pushMessage(
                f'[CRS Magic finder] {message}',
                Qgis.MessageLevel.Info,
                8,
            )

        def status_changed(status):
            if status==3:
                self.schedule_transform_message_interception_stop()
                fk_b_s=r'<span style="color:black">'
                fk_r_s='<span style="color:red">'
                fk_e=r'</span>'
                self.clearMBar()
                if self.results_dialog:
                    self.results_dialog.mark_finished()
                #print("Завершено!")
                #print('Звіт:')
                #print(task.message)
                result_message=f'[CRS Magic finder] Перевірте результат підбору СК за фотопланом.\r\n\r\n'
                number=1
                automatic_changes = []
                
                for layer in self.selected_layers:
                    result_message=result_message+f'\r\n{number}. '
                    number=number+1
                    layer_id=layer.id()
                    layer_result = task.result_for_layer(layer_id)
                    if layer_result and layer_result['Checked']:
                        if 'PossibleCRS' in layer_result:
                            if self.results_dialog and self.results_dialog.has_manual_selection(layer_id):
                                crs=self.results_dialog.manual_selection_text(layer_id)
                                result_message=result_message+f"{fk_b_s}Шар «{layer.name()}»:\r\n СК вручну змінено на {crs}.{fk_e}\r\n"
                            else:
                                crs=layer_result['PossibleCRS']
                                other_crs=layer_result['OtherPossibleCRS']
                                found_crs=layer_result['FoundCRS']
                                old_crs = QgsCoordinateReferenceSystem(layer.crs())
                                layer.setCrs(found_crs)
                                if old_crs != found_crs:
                                    automatic_changes.append((layer, old_crs, found_crs))
                                result_message=result_message+f"{fk_b_s}Шар «{layer.name()}»:\r\n СК змінено на {crs}. {other_crs}{fk_e}\r\n"
                        else:
                            result_message=result_message+f"{fk_r_s}Шар «{layer.name()}»: помилка підбору СК — {layer_result['Error']}{fk_e}\r\n"
                            
                    elif layer.type() not in (QgsMapLayerType.VectorLayer, QgsMapLayerType.RasterLayer):
                        result_message=result_message+f"{fk_r_s}Шар «{layer.name()}» не перевірено, оскільки він не є векторним або растровим.{fk_e}\r\n"
                        
                if self.results_dialog and automatic_changes:
                    self.results_dialog.record_external_changes(automatic_changes)

                for changed_layer, old_crs, new_crs in automatic_changes:
                    changed_layer.triggerRepaint(True)
                if automatic_changes:
                    canvas.refresh()
                self.clearMBar()
                message_bar.pushMessage("[CRS Magic finder] Підбір СК завершено. Результати доступні в таблиці.", Qgis.MessageLevel.Success, 5)
                if geographic_warnings:
                    message_bar.pushMessage(
                        '[CRS Magic finder] ' + ' '.join(geographic_warnings),
                        Qgis.MessageLevel.Info,
                        10,
                    )
                if task.fallback_crs_qty:
                    message_bar.pushMessage(
                        '[CRS Magic finder] Під час підбору використано запасні '
                        f'перетворення (Fallback): {task.fallback_crs_qty}. '
                        'Перевірте результат за надійною картографічною підкладкою.',
                        Qgis.MessageLevel.Warning,
                        10,
                    )
                print(result_message)
                # if len(self.selected_layers)>0:
                    # custom_message_box = CustomMessageBox('Готово!', result_message)
                    # custom_message_box.exec_()
                # else:
                    # message_bar.pushMessage(result_message, Qgis.MessageLevel.Success,0)
                    # print(result_message)
                self.activated=False
                self.action_reference.setChecked(False)
                self.iface.mapCanvas().unsetMapTool(self.iface.mapCanvas().mapTool())
                # print(task.message)
                return
            if status==4:
                self.schedule_transform_message_interception_stop()
                self.clearMBar()
                # print(task.message)
                # print(task.last_action)
                if task.isCanceled():
                    if self.results_dialog:
                        self.results_dialog.mark_failed('Підбір СК скасовано користувачем')
                    print("Скасовано користувачем")
                else:
                    if task.getFailure():                            
                        failure=task.getFailure()
                    else:
                        failure="Сталася помилка. Повторіть спробу."
                    if self.results_dialog:
                        self.results_dialog.mark_failed(failure)
                    print(f"[CRS Magic finder] {failure}")
                    print(task.message)
                    message_bar.pushMessage(f"[CRS Magic finder] {failure}", Qgis.MessageLevel.Warning, 5)                        
                
        self.clearMBar()
        message_bar = self.iface.messageBar()
        #print(f'Точка кліку до входження в задачу: {click_point.toString(4)}')
        project = QgsProject.instance()
        transform_context = QgsCoordinateTransformContext(project.transformContext())
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()        
        work_crs = QgsCoordinateReferenceSystem('EPSG:3857')
        
        transformation = QgsCoordinateTransform(canvas_crs, work_crs, project)
        self.configure_transform_fallback(transformation)
        tr_click_point=transformation.transform(click_point)
        
        crs_codes = self.active_crs_codes()
        crs_set_name = self.active_crs_set_label()
        layer_inputs = []
        for layer in self.layers:
            layer_input = {
                'id': layer.id(),
                'name': layer.name(),
                'type': layer.type(),
                'feature_source': None,
                'extent': None,
            }
            if layer.type() == QgsMapLayerType.VectorLayer:
                try:
                    layer_input['feature_source'] = QgsVectorLayerFeatureSource(layer)
                except Exception:
                    layer_input['feature_source'] = None
            if layer.type() == QgsMapLayerType.RasterLayer:
                try:
                    layer_input['extent'] = QgsRectangle(layer.extent())
                except Exception:
                    layer_input['extent'] = None
            layer_inputs.append(layer_input)

        message_bar.pushMessage(f'[CRS Magic finder] Триває підбір СК. Зачекайте, будь ласка. Набір: {crs_set_name}', Qgis.MessageLevel.Success,0)
        
        if self.results_dialog:
            self.results_dialog.close()
        self.results_dialog = CRSResultsDialog(self.layers, self.iface, self.iface.mainWindow())
        self.results_dialog.show()

        task = findCrs(
            "Пошук можливих систем координат",
            layer_inputs,
            tr_click_point,
            work_crs,
            crs_codes,
            crs_set_name,
            self.fast_mode,
            self.group_search,
            self.disable_fallback_handler,
            self.allow_fallback,
            self.allow_ballpark,
            self.filter_by_crs_bounds,
            transform_context,
        )
        self.results_dialog.set_task(task)
        task.groupsPrepared.connect(self.results_dialog.set_search_units)
        task.crsChecked.connect(self.results_dialog.add_result)
        task.statsChanged.connect(self.results_dialog.update_stats)
        task.geographicCrsSkipped.connect(show_geographic_warning)
        
        task.statusChanged.connect(status_changed)
        task.setDependentLayers(self.layers)
        self.start_transform_message_interception()
        try:
            QgsApplication.taskManager().addTask(task)
        except Exception:
            self.stop_transform_message_interception()
            raise
        
        print('Запускаю процес підбору...')
    
    
    def Run(self):
        # simple_search=False
        
        # if self.isControlOrShift()=='shift':#якщо зажато шифт - виконуємо підбір по центру екстенту
            # simple_search=True            
        
        message_bar = self.iface.messageBar()
        self.clearMBar()
        
        if self.activated:#Якщо увімкнено то вимикаємо і відключаємо інструмент
            self.activated=False
            self.action_reference.setChecked(False)
            self.iface.mapCanvas().unsetMapTool(self.pointTool)            
            return
        
        layers=[]
        
        selected_layers = self.iface.layerTreeView().selectedLayersRecursive()
        
        if len(selected_layers)<1:
            message_bar.pushMessage("[CRS Magic finder] Спочатку виділіть векторні або растрові шари в панелі шарів.", Qgis.MessageLevel.Warning, 5)
            self.action_reference.setChecked(False)
            return
        
        for layer in selected_layers:
            if layer.type() == QgsMapLayerType.VectorLayer and layer.isValid():
                layers.append(layer)
            elif layer.type() == QgsMapLayerType.RasterLayer and layer.isValid():
                layers.append(layer)
        
        if len(layers)<1:
            message_bar.pushMessage("[CRS Magic finder] Серед вибраних немає придатних векторних або растрових шарів для аналізу.", Qgis.MessageLevel.Warning, 5)
            self.action_reference.setChecked(False)
            return
        
        # if self.isControlOrShift()=='ctrl':
            # self.visualizeExtent(layers)
            # self.action_reference.setChecked(False)
            # return
        
        layers_warning=''
        if not all(element in layers for element in selected_layers):
            layers_warning=" Частину вибраних шарів пропущено: вони мають непідтримуваний тип, є некоректними або порожніми."
        
        self.activated=True
        self.action_reference.setChecked(True)
        crs_set_name = self.active_crs_set_label()
        
        if len(layers)==1:
            message_bar.pushMessage(f"[CRS Magic finder] Клацніть на карті, щоб указати орієнтовне місце розташування об’єктів шару «{layers[0].name()}».{layers_warning} Набір СК: {crs_set_name}", Qgis.MessageLevel.Info, 0)
        else:
            message_bar.pushMessage(f"[CRS Magic finder] Клацніть на карті, щоб указати орієнтовне місце розташування об’єктів вибраних шарів. Вибрано шарів: {len(selected_layers)}.{layers_warning} Набір СК: {crs_set_name}", Qgis.MessageLevel.Info, 0)
        
        self.layers=layers
        self.selected_layers=selected_layers
        
        self.iface.mapCanvas().setMapTool(self.pointTool)
        

    def tool_chaged(self):
        self.activated=False
        self.action_reference.setChecked(False)
        self.clearMBar()
    
    def isControlOrShift(self):
        ctrl_pressed = Qt.ControlModifier & QApplication.keyboardModifiers()
        shift_pressed = Qt.ShiftModifier & QApplication.keyboardModifiers()
            
        if ctrl_pressed and shift_pressed:
            print('ctrl+shift')
            return 'ctrl+shift'
        elif ctrl_pressed:
            print('ctrl')
            return 'ctrl'
        elif shift_pressed:
            print('shift')
            return 'shift'
        else:
            return False
    
    def visualizeExtent(self, layers):
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()

        # Create a rubber band for the total extent
        total_rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        total_extent = QgsRectangle()

        for current_layer in layers:
            layer_extent = current_layer.extent()

            # Transform layer extent to canvas CRS
            transform = QgsCoordinateTransform(current_layer.crs(), canvas_crs, QgsProject.instance())
            layer_extent = transform.transformBoundingBox(layer_extent)
            # Combine the layer geometry with the total extent
            total_extent.combineExtentWith(layer_extent)

        # Set the geometry of the total rubber band
        total_rubber_band.setToGeometry(QgsGeometry.fromRect(total_extent).convertToType(QgsWkbTypes.LineGeometry), None)

        # Set the color and width of the total rubber band
        total_rubber_band.setColor(Qt.red)
        total_rubber_band.setWidth(1)        
        # Reset the total rubber band after a timeout
        def aaa():
            canvas = self.iface.mapCanvas()

            # Get all rubber bands on the canvas
            rubber_bands = [item for item in canvas.scene().items() if isinstance(item, QgsRubberBand)]

            # Remove each rubber band
            for band in rubber_bands:
                band.reset()

            # Refresh the canvas
            canvas.refresh()
        timer = QTimer()
        timer.timeout.connect(aaa)
        timer.start(10)  # Adjust the timeout as needed

        # Set the extent and zoom the canvas
        canvas.setExtent(total_extent)
        canvas.zoomScale(canvas.scale() * 1.5)
        canvas.refresh()
    
   
