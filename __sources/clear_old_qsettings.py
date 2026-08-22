from qgis.PyQt.QtCore import QSettings


settings = QSettings()
legacy_keys = (
    'CRS_Magic/crs_sets',
    'CRS_Magic/crs_set_metadata',
    'CRS_Magic/default_sets/ukrainian_version',
)

for key in legacy_keys:
    settings.remove(key)

settings.sync()
print('Видалено старі гілки QSettings:')
for key in legacy_keys:
    print(f'  {key}')
print(f'Файл налаштувань: {settings.fileName()}')
