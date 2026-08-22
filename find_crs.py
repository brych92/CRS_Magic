import math
import random
import statistics

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsMapLayerType,
    QgsPointXY,
    QgsRectangle,
    QgsTask,
)
from qgis.PyQt.QtCore import pyqtSignal


class findCrs(QgsTask):
    crsChecked = pyqtSignal(str, str, str, str, int, object, str)
    statsChanged = pyqtSignal(int, int, int, int, int, int)
    groupsPrepared = pyqtSignal(object)
    geographicCrsSkipped = pyqtSignal(str)

    def __init__(
        self,
        description,
        layer_inputs,
        click_point,
        canvas_crs,
        crs_codes=None,
        crs_set_name='Усі СК',
        fast_mode=False,
        group_search=False,
        disable_fallback_handler=True,
        allow_fallback=True,
        allow_ballpark=False,
        transform_context=None,
    ):
        super().__init__(description, QgsTask.CanCancel)        
        self.status = None
        
        self.layer_inputs = layer_inputs
        self.layers_qty = len(layer_inputs)
        
        self.canvas_crs = canvas_crs        
        self.click_point = click_point
        self.crs_codes = self.normalize_crs_codes(crs_codes) if crs_codes is not None else None
        self.crs_set_name = crs_set_name or 'Усі СК'
        self.fast_mode = bool(fast_mode)
        self.group_search = bool(group_search)
        self.disable_fallback_handler = bool(disable_fallback_handler)
        self.allow_fallback = bool(allow_fallback)
        self.allow_ballpark = bool(allow_ballpark)
        self.project_transform_context = transform_context
        
        self.failure_reason=None
        self.result=None
        self.skipped_crs_qty=0
        self.unit_filtered_crs_qty=0
        self.max_result_distance=200000
        self.near_origin_threshold=10000
        self.total_crs_to_check=0
        self.processed_crs_qty=0
        self.success_crs_qty=0
        self.failed_crs_qty=0
        self.matched_crs_qty=0
        self.fallback_crs_qty=0
        # Підготовка центрів зазвичай значно коротша за перевірку тисяч СК,
        # тому вона займає лише перші 5% індикатора. Останній відсоток
        # залишається для формування підсумку після перевірки кандидатів.
        self.initial_progress=0
        self.center_progress_weight=5
        self.crs_progress_weight=94
        
        self.message=''
        
        """
        Історичні ручні PROJ-операції вимкнено. Блок залишено як довідковий:
        усі можливі СК тепер використовують стандартні операції QGIS/PROJ.

        self.proj_list={'EPSG:3857' : '+proj=noop', #proj коди перетворень, без них на версії 3.22 не працювало
            'EPSG:4326' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5562' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=21 +k=1 +x_0=4500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.322 +y=-121.372 +z=-75.847 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5563' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=5500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5564' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33 +k=1 +x_0=6500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5565' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=7500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5566' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=21 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5567' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5568' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5569' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5576' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=13500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5577' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=21 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5578' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=24 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5579' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5580' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=30 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5581' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5582' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=36 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5583' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=500000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6381' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=21 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6382' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=24 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6383' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6384' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=30 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6385' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6386' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=36 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:6387' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5558' : '+proj=pipeline +step +inv +proj=cart +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5560' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +z_in=m +xy_out=rad +z_out=m +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:5561' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9821' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=30.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9831' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=34.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9832' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=28.6666666666667 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9833' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=24.8333333333333 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9834' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=35 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9835' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=37.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9836' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=28.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9837' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=23.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9838' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=36 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9839' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=24.75 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9840' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=32 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9841' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9842' : '+proj=pipeline +step +inv +proj=lcc +lat_0=42 +lon_0=3 +lat_1=41.25 +lat_2=42.75 +x_0=1700000 +y_0=1200000 +ellps=GRS80 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9843' : '+proj=pipeline +step +inv +proj=lcc +lat_0=43 +lon_0=3 +lat_1=42.25 +lat_2=43.75 +x_0=1700000 +y_0=2200000 +ellps=GRS80 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9851' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=24 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9852' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=31.8333333333333 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9853' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=30 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9854' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33.8333333333333 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9855' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9856' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=34.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9857' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=25.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9858' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=36.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9859' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9860' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=27 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9861' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=31.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9862' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=26 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9863' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=32 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9864' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=30.5 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:9865' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0 +lon_0=33 +k=1 +x_0=300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=24.353 +y=-121.36 +z=-75.968 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:4284' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=25 +y=-141 +z=-78.5 +rx=0 +ry=-0.35 +rz=-0.736 +s=0 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:4179' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=2.329 +y=-147.042 +z=-92.08 +rx=0.309 +ry=-0.325 +rz=-0.497 +s=5.69 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:4178' : '+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=26 +y=-121 +z=-78 +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7825' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=23.5 +k=1 +x_0=1300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7826' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=26.5 +k=1 +x_0=2300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7827' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=29.5 +k=1 +x_0=3300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7828' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=32.5 +k=1 +x_0=4300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7829' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=35.5 +k=1 +x_0=5300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7830' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=38.5 +k=1 +x_0=6300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84',
            'EPSG:7831' : '+proj=pipeline +step +inv +proj=tmerc +lat_0=0.0833333333333333 +lon_0=41.5 +k=1 +x_0=7300000 +y_0=0 +ellps=krass +step +proj=push +v_3 +step +proj=cart +ellps=krass +step +proj=helmert +x=23.57 +y=-140.95 +z=-79.8 +rx=0 +ry=-0.35 +rz=-0.79 +s=-0.22 +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84 +step +proj=pop +v_3 +step +proj=webmerc +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84'
            }
        """
        self.proj_list = {}
        
        
        self.total_result = {}
        self.layer_to_unit = {}
        self.search_units = []
        self.transformContext = None
        self.distance_calculator = None
    
    def normalize_crs_codes(self, crs_codes):
        result = []
        known_codes = set()
        for crs_code in crs_codes or []:
            code = str(crs_code).strip().upper()
            if code.isdigit():
                code = f'EPSG:{code}'
            if code and code not in known_codes:
                result.append(code)
                known_codes.add(code)
        return result

    def initialize_transform_tools(self):
        if self.project_transform_context is None:
            self.transformContext = QgsCoordinateTransformContext()
        else:
            self.transformContext = QgsCoordinateTransformContext(
                self.project_transform_context
            )

        self.distance_calculator = QgsDistanceArea()
        self.distance_calculator.setSourceCrs(self.canvas_crs, self.transformContext)
        self.distance_calculator.setEllipsoid('WGS84')


    def getFailure(self):
        return self.failure_reason

    def emit_stats(self):
        self.statsChanged.emit(
            self.total_crs_to_check,
            self.processed_crs_qty,
            self.success_crs_qty,
            self.failed_crs_qty,
            self.skipped_crs_qty,
            self.matched_crs_qty
        )

    def result_for_layer(self, layer_id):
        unit_id = self.layer_to_unit.get(layer_id, layer_id)
        return self.total_result.get(unit_id)

    def extent_diagonal(self, extent):
        if extent is None:
            return 0.0
        try:
            width = abs(extent.width())
            height = abs(extent.height())
            if not (math.isfinite(width) and math.isfinite(height)):
                return 0.0
            return math.hypot(width, height)
        except Exception:
            return 0.0

    def extents_intersect(self, left_extent, right_extent):
        if left_extent is None or right_extent is None:
            return False
        try:
            return not (
                left_extent.xMaximum() < right_extent.xMinimum()
                or right_extent.xMaximum() < left_extent.xMinimum()
                or left_extent.yMaximum() < right_extent.yMinimum()
                or right_extent.yMaximum() < left_extent.yMinimum()
            )
        except Exception:
            return False

    def build_search_units(self, centers, object_extents):
        layer_inputs = {item['id']: item for item in self.layer_inputs}
        ordered_ids = [item['id'] for item in self.layer_inputs]
        valid_ids = [layer_id for layer_id in ordered_ids if layer_id in centers]
        diagonals = {
            layer_id: self.extent_diagonal(object_extents.get(layer_id))
            for layer_id in valid_ids
        }

        if self.group_search and len(valid_ids) > 1:
            remaining_ids = list(valid_ids)
            components = []
            order = {layer_id: index for index, layer_id in enumerate(ordered_ids)}
            while remaining_ids:
                anchor_id = max(
                    remaining_ids,
                    key=lambda layer_id: (diagonals[layer_id], -order[layer_id]),
                )
                anchor_extent = object_extents.get(anchor_id)
                member_ids = [
                    layer_id
                    for layer_id in remaining_ids
                    if layer_id == anchor_id
                    or self.extents_intersect(
                        anchor_extent,
                        object_extents.get(layer_id),
                    )
                ]
                member_ids.sort(key=order.get)
                components.append(member_ids)
                member_set = set(member_ids)
                remaining_ids = [
                    layer_id
                    for layer_id in remaining_ids
                    if layer_id not in member_set
                ]
        else:
            components = [[layer_id] for layer_id in valid_ids]

        component_by_layer = {}
        for member_ids in components:
            for layer_id in member_ids:
                component_by_layer[layer_id] = member_ids

        units = []
        search_centers = {}
        emitted_components = set()
        for layer_id in ordered_ids:
            if layer_id not in centers:
                layer_name = layer_inputs[layer_id]['name']
                self.layer_to_unit[layer_id] = layer_id
                self.total_result[layer_id]['LayerIds'] = [layer_id]
                units.append({
                    'id': layer_id,
                    'name': layer_name,
                    'layer_ids': [layer_id],
                    'grouped': False,
                    'near_origin_warning': False,
                    'center_coordinates': None,
                    'extent_diagonal': self.extent_diagonal(
                        object_extents.get(layer_id)
                    ),
                })
                continue

            member_ids = component_by_layer[layer_id]
            component_key = tuple(member_ids)
            if component_key in emitted_components:
                continue
            emitted_components.add(component_key)

            grouped = len(member_ids) > 1
            if grouped:
                unit_id = 'group:' + '|'.join(sorted(member_ids))
                layer_names = [layer_inputs[item_id]['name'] for item_id in member_ids]
                unit_name = f"Група ({len(member_ids)}): {', '.join(layer_names)}"
                unit_center = QgsPointXY(
                    statistics.median(centers[item_id].x() for item_id in member_ids),
                    statistics.median(centers[item_id].y() for item_id in member_ids),
                )
                self.total_result[unit_id] = {
                    'LayerName': unit_name,
                    'LayerIds': list(member_ids),
                    'Checked': True,
                }
            else:
                unit_id = member_ids[0]
                unit_name = layer_inputs[unit_id]['name']
                unit_center = centers[unit_id]
                self.total_result[unit_id]['LayerIds'] = [unit_id]

            for member_id in member_ids:
                self.layer_to_unit[member_id] = unit_id

            search_centers[unit_id] = unit_center
            units.append({
                'id': unit_id,
                'name': unit_name,
                'layer_ids': list(member_ids),
                'grouped': grouped,
                'near_origin_warning': self.centroid_is_near_coordinate_origin(
                    unit_center
                ),
                'center_coordinates': (unit_center.x(), unit_center.y()),
                'extent_diagonal': max(diagonals[item_id] for item_id in member_ids),
            })

        return units, search_centers
    
    def run(self):
        try:
            self.setProgress(self.initial_progress)
            self.initialize_transform_tools()
            self.message = self.message + f'СК проєкту: {self.canvas_crs.authid()}\r\n'
            self.message = self.message + f'Точка кліку: {self.click_point.toString(4)}\r\n'
            self.message = self.message + 'Режим визначення центру: стійкий до викидів\r\n'

            centers = {}
            object_extents = {}
            for layer_index, layer_input in enumerate(self.layer_inputs, start=1):
                layer_id = layer_input['id']
                layer_name = layer_input['name']
                self.message = self.message + (
                    f'\r\nПеревіряємо шар: {layer_name}\r\n'
                    '*************************************************************\r'
                )

                self.total_result[layer_id] = {
                    'LayerName': layer_name,
                    'Checked': True,
                }

                center, object_extent, center_error = self.find_center(layer_input)
                if self.isCanceled():
                    self.failure_reason='Підбір СК скасовано користувачем'
                    return False

                # Навіть порожній або пошкоджений шар має завершити свою
                # частину етапу підготовки, щоб прогрес не залежав від помилки.
                preparation_progress = (
                    self.initial_progress
                    + self.center_progress_weight
                    * layer_index
                    / max(1, self.layers_qty)
                )
                self.setProgress(max(self.progress(), preparation_progress))

                if center is not None:
                    centers[layer_id] = center
                    if object_extent is not None:
                        object_extents[layer_id] = object_extent
                    if not self.centroid_can_be_geographic(center):
                        self.geographicCrsSkipped.emit(
                            f"Шар «{layer_name}»: координати центру не відповідають "
                            'діапазонам довготи й широти, тому географічні СК для нього '
                            'будуть пропущені.'
                        )
                    self.message = self.message + (
                        f'Центр шару: {center.toString(4)}\r\n'
                        '===============================================================\r\n'
                    )
                else:
                    self.total_result[layer_id]['Error'] = center_error
                    self.message = self.message + (
                        f'Центр шару не визначено: {center_error}\r\n'
                        '===============================================================\r\n'
                    )

            search_units, search_centers = self.build_search_units(
                centers,
                object_extents,
            )
            self.search_units = search_units
            self.groupsPrepared.emit(search_units)

            if not search_centers:
                self.failure_reason = 'Не вдалося визначити центр жодного шару'
                return False

            if not self.range_distances(search_centers, self.click_point):
                return False

            self.setProgress(100)
            return True
        except Exception as e:
            self.failure_reason=f'Помилка підбору СК: {type(e).__name__}: {str(e)}'
            self.message=self.message+self.failure_reason+'\r\n'
            return False
    
    def crs_from_proj(self, crs):
        try:
            proj_string = crs.toProj()
        except Exception:
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_string:
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        proj_crs = QgsCoordinateReferenceSystem()
        try:
            proj_created = proj_crs.createFromProj(proj_string, False)
        except TypeError:
            if hasattr(proj_crs, 'createFromProj4'):
                proj_created = proj_crs.createFromProj4(proj_string)
            else:
                proj_created = proj_crs.createFromProj(proj_string)
        except Exception:
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_created:
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_crs.isValid():
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        return proj_crs

    def format_crs_result(self, crs_result):
        crs_code, crs_name, distance = crs_result[0], crs_result[1], crs_result[2]
        return f"{self.format_crs_label(crs_code, crs_name)} — {f'{distance:,.0f}'.replace(',', ' ')} м від точки кліку"

    def crs_name(self, crs):
        try:
            return crs.description()
        except Exception:
            return ''

    def format_crs_label(self, crs_code, crs_name):
        if crs_name:
            return f'{crs_code} — {crs_name}'
        return crs_code

    def crs_for_layer(self, crs, crs_code):
        layer_crs = QgsCoordinateReferenceSystem(crs_code)
        if layer_crs.isValid():
            return layer_crs

        try:
            layer_crs = QgsCoordinateReferenceSystem.fromSrsId(crs.srsid())
            if layer_crs.isValid():
                return layer_crs
        except Exception:
            pass

        return crs

    def centroid_can_be_geographic(self, centroid):
        x = abs(centroid.x())
        y = abs(centroid.y())
        return (x <= 180 and y <= 90) or (x <= 90 and y <= 180)

    def centroid_is_near_coordinate_origin(self, centroid):
        if centroid is None or self.centroid_can_be_geographic(centroid):
            return False
        try:
            return math.hypot(centroid.x(), centroid.y()) <= self.near_origin_threshold
        except Exception:
            return False

    def should_skip_crs_by_centroid_units(self, crs, centroid):
        try:
            return crs.isGeographic() and not self.centroid_can_be_geographic(centroid)
        except Exception:
            return False

    def configure_transform_fallback(self, transformation):
        transformation.disableFallbackOperationHandler(self.disable_fallback_handler)
        transformation.setAllowFallbackTransforms(self.allow_fallback)
        transformation.setBallparkTransformsAreAppropriate(self.allow_ballpark)

    def transform_note(self, transformation):
        if not self.disable_fallback_handler:
            return ''

        try:
            fallback_occurred = transformation.fallbackOperationOccurred()
        except Exception:
            fallback_occurred = False

        if not fallback_occurred:
            return ''
        if self.allow_ballpark:
            return 'Ballpark'
        return 'Fallback'

    def range_distances(self, centers, click_point):
        self.skipped_crs_qty=0
        self.unit_filtered_crs_qty=0
        distance_results = {layer_id: [] for layer_id in centers}
        known_crs=set()

        srs_ids = []
        selected_crs_mode = self.crs_codes is not None
        if selected_crs_mode:
            total_crs_qty=len(self.crs_codes)
            self.message=self.message+f'Перевіряємо {total_crs_qty} СК з набору "{self.crs_set_name}"\r\n'
        else:
            try:
                srs_ids = QgsCoordinateReferenceSystem.validSrsIds()
            except Exception:
                srs_ids = []
                self.skipped_crs_qty=self.skipped_crs_qty+1

            total_crs_qty=len(srs_ids)
            self.message=self.message+f'Перевіряємо до {total_crs_qty} СК з бази QGIS\r\n'

        self.total_crs_to_check = total_crs_qty
        self.emit_stats()

        if total_crs_qty == 0:
            if selected_crs_mode:
                self.failure_reason='Активний набір СК не містить кодів для перевірки'
            else:
                self.failure_reason='У базі QGIS не знайдено коректних СК для перевірки'
            return None

        search_start_progress = self.progress()

        def update_search_progress():
            self.setProgress(
                search_start_progress
                + self.crs_progress_weight
                * self.processed_crs_qty
                / total_crs_qty
            )

        def process_crs(crs_code, crs):
            if self.isCanceled():
                self.failure_reason='Підбір СК скасовано користувачем'
                return False

            try:
                if not crs.isValid():
                    self.failed_crs_qty=self.failed_crs_qty+1
                    return True

                real_crs_code = crs.authid() or crs_code
                real_crs_name = self.crs_name(crs)
                if real_crs_code in known_crs:
                    self.skipped_crs_qty += 1
                    return True

                applicable_centers = {
                    layer_id: center
                    for layer_id, center in centers.items()
                    if not self.should_skip_crs_by_centroid_units(crs, center)
                }
                self.unit_filtered_crs_qty += len(centers) - len(applicable_centers)
                if not applicable_centers:
                    self.skipped_crs_qty += 1
                    return True

                if self.fast_mode:
                    source_crs = crs
                else:
                    source_crs = self.crs_from_proj(crs)
                    if not source_crs:
                        return True

                layer_crs = self.crs_for_layer(crs, real_crs_code)
                known_crs.add(real_crs_code)

                xform = QgsCoordinateTransform(source_crs, self.canvas_crs, self.transformContext)
                self.configure_transform_fallback(xform)

                candidate_succeeded = False
                for layer_id, center in applicable_centers.items():
                    try:
                        transformed_center = xform.transform(center)
                        transform_note = self.transform_note(xform)
                        if transform_note:
                            self.fallback_crs_qty += 1
                        if not (
                            math.isfinite(transformed_center.x())
                            and math.isfinite(transformed_center.y())
                        ):
                            continue

                        candidate_succeeded = True
                        distance = self.distance_calculator.measureLine(
                            click_point,
                            transformed_center,
                        )
                        if not math.isfinite(distance) or distance < 0:
                            continue
                        if distance >= self.max_result_distance:
                            continue

                        int_distance = int(distance)
                        self.matched_crs_qty += 1
                        crs_result = (
                            real_crs_code,
                            real_crs_name,
                            int_distance,
                            layer_crs,
                            transform_note,
                        )
                        distance_results[layer_id].append(crs_result)
                        layer_name = self.total_result[layer_id]['LayerName']
                        self.crsChecked.emit(
                            layer_id,
                            layer_name,
                            real_crs_code,
                            real_crs_name,
                            int_distance,
                            layer_crs,
                            transform_note,
                        )
                    except Exception:
                        continue

                if candidate_succeeded:
                    self.success_crs_qty += 1
                else:
                    self.failed_crs_qty += 1
            except Exception:
                self.failed_crs_qty=self.failed_crs_qty+1

            return True

        if selected_crs_mode:
            for crs_code in self.crs_codes:
                try:
                    if crs_code.startswith('QGIS:'):
                        srs_id = int(crs_code.split(':', 1)[1])
                        crs = QgsCoordinateReferenceSystem.fromSrsId(srs_id)
                    else:
                        crs = QgsCoordinateReferenceSystem(crs_code)
                    if not process_crs(crs_code, crs):
                        return None
                except Exception:
                    self.failed_crs_qty=self.failed_crs_qty+1

                self.processed_crs_qty=self.processed_crs_qty+1
                self.emit_stats()
                update_search_progress()
        else:
            for srs_id in srs_ids:
                try:
                    crs = QgsCoordinateReferenceSystem.fromSrsId(srs_id)
                    crs_code = crs.authid() or f'QGIS:{crs.srsid()}'
                    if not process_crs(crs_code, crs):
                        return None
                except Exception:
                    self.failed_crs_qty=self.failed_crs_qty+1

                self.processed_crs_qty=self.processed_crs_qty+1
                self.emit_stats()
                update_search_progress()
            
        for layer_id, layer_results in distance_results.items():
            if not layer_results:
                if 'Error' not in self.total_result[layer_id]:
                    self.total_result[layer_id]['Error'] = (
                        'Не вдалося підібрати СК у радіусі 200 км. '
                        'Дані можуть бути в умовній СК або містити некоректні геометрії.'
                    )
                continue

            ordered_results = sorted(layer_results, key=lambda result: result[2])
            found_crs = ordered_results[0][3]
            self.total_result[layer_id]['FoundCRS'] = found_crs
            self.total_result[layer_id]['PossibleCRS'] = self.format_crs_result(ordered_results[0])
            if len(ordered_results) > 1:
                possible_crs = '\r\n'.join(
                    self.format_crs_result(result) for result in ordered_results[1:]
                )
                self.total_result[layer_id]['OtherPossibleCRS'] = (
                    f'\r\n\tІнші можливі СК:\r\n {possible_crs}'
                )
            else:
                self.total_result[layer_id]['OtherPossibleCRS'] = ''

        if self.skipped_crs_qty:
            self.message = self.message + (
                f'Пропущено СК під час перевірки: {self.skipped_crs_qty}\r\n'
            )
        if self.unit_filtered_crs_qty:
            self.message = self.message + (
                'Пропущено географічні СК для центрів із метричними координатами: '
                f'{self.unit_filtered_crs_qty}\r\n'
            )
        if self.fallback_crs_qty:
            self.message = self.message + (
                'Використано запасних перетворень (Fallback): '
                f'{self.fallback_crs_qty}\r\n'
            )
        return True
        
    def find_center(self, layer_input):
        layer_type = layer_input['type']
        layer_progress = self.center_progress_weight / max(1, self.layers_qty)
        start_progress = self.progress()

        if layer_type == QgsMapLayerType.RasterLayer:
            extent = layer_input.get('extent')
            try:
                if extent is None:
                    return None, None, 'Екстент растрового шару не визначено'
                coordinates = (
                    extent.xMinimum(),
                    extent.yMinimum(),
                    extent.xMaximum(),
                    extent.yMaximum(),
                )
                if (
                    extent.isEmpty()
                    or not all(math.isfinite(value) for value in coordinates)
                    or extent.width() <= 0
                    or extent.height() <= 0
                ):
                    return None, None, 'Екстент растрового шару не визначено'

                self.setProgress(start_progress + layer_progress)
                return QgsPointXY(extent.center()), QgsRectangle(extent), None
            except Exception:
                return (
                    None,
                    None,
                    'Не вдалося визначити центр екстенту растрового шару',
                )

        if layer_type != QgsMapLayerType.VectorLayer:
            return None, None, 'Тип шару не підтримується'

        feature_source = layer_input.get('feature_source')
        if feature_source is None:
            return (
                None,
                None,
                'Не вдалося підготувати об’єкти векторного шару до аналізу',
            )

        try:
            feature_qty = feature_source.featureCount()
        except Exception:
            feature_qty = -1
        if feature_qty == 0:
            return None, None, 'У векторному шарі відсутні об’єкти'

        request = QgsFeatureRequest()
        request.setNoAttributes()
        update_interval = max(1, feature_qty // 100) if feature_qty > 0 else 100
        processed_features = 0
        usable_centers = 0
        robust_sample = []
        object_bounds = None
        sample_limit = 4096
        randomizer = random.Random(0)

        for feature in feature_source.getFeatures(request):
            if self.isCanceled():
                return None, None, 'Підбір СК скасовано користувачем'

            processed_features += 1
            if feature.hasGeometry():
                point, feature_extent = self.feature_center_and_extent(
                    feature.geometry()
                )
                if point is not None and feature_extent is not None:
                    feature_bounds = (
                        feature_extent.xMinimum(),
                        feature_extent.yMinimum(),
                        feature_extent.xMaximum(),
                        feature_extent.yMaximum(),
                    )
                    if object_bounds is None:
                        object_bounds = list(feature_bounds)
                    else:
                        object_bounds[0] = min(object_bounds[0], feature_bounds[0])
                        object_bounds[1] = min(object_bounds[1], feature_bounds[1])
                        object_bounds[2] = max(object_bounds[2], feature_bounds[2])
                        object_bounds[3] = max(object_bounds[3], feature_bounds[3])
                    usable_centers += 1
                    if len(robust_sample) < sample_limit:
                        robust_sample.append((point.x(), point.y()))
                    else:
                        replace_index = randomizer.randrange(usable_centers)
                        if replace_index < sample_limit:
                            robust_sample[replace_index] = (point.x(), point.y())

            if feature_qty > 0 and (
                processed_features % update_interval == 0
                or processed_features == feature_qty
            ):
                fraction = min(1.0, processed_features / feature_qty)
                self.setProgress(start_progress + layer_progress * fraction)

        if usable_centers == 0:
            return (
                None,
                None,
                'Не вдалося визначити центр: об’єкти не мають придатної геометрії',
            )

        center = QgsPointXY(
            statistics.median(point[0] for point in robust_sample),
            statistics.median(point[1] for point in robust_sample),
        )
        object_extent = QgsRectangle(*object_bounds)

        self.setProgress(start_progress + layer_progress)
        return center, object_extent, None

    def feature_center_and_extent(self, geometry):
        try:
            if geometry is None or geometry.isEmpty():
                return None, None

            extent = geometry.boundingBox()
            coordinates = (
                extent.xMinimum(),
                extent.yMinimum(),
                extent.xMaximum(),
                extent.yMaximum(),
            )
            if not all(math.isfinite(value) for value in coordinates):
                return None, None
            point = extent.center()

            if not (math.isfinite(point.x()) and math.isfinite(point.y())):
                return None, None
            return QgsPointXY(point), QgsRectangle(extent)
        except Exception:
            return None, None
            
