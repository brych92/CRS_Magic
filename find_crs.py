from qgis.core import QgsTask, QgsCoordinateTransform, \
    QgsCsException, QgsCoordinateReferenceSystem, \
    QgsGeometry, QgsDistanceArea, QgsCoordinateTransformContext, QgsUnitTypes, QgsPoint, QgsPointXY
from qgis.PyQt.QtCore import pyqtSignal


class findCrs(QgsTask):
    crsChecked = pyqtSignal(str, str, str, str, int, object)
    statsChanged = pyqtSignal(int, int, int, int, int)

    def __init__(self, description, layers, click_point, canvas_crs, project, crs_codes=None, crs_set_name='Всі СК'):
        super().__init__(description, QgsTask.CanCancel)        
        self.status = None
        
        self.layers = layers #шари для яких буде підбиратися СК
        self.layers_qty=len(layers)
        
        self.canvas_crs = canvas_crs        
        self.project = project
        self.click_point = click_point
        self.crs_codes = self.normalize_crs_codes(crs_codes) if crs_codes is not None else None
        self.crs_set_name = crs_set_name or 'Всі СК'
        #self.simple_search = simple_search Тут був прискорений пошук за центроїдом екстенту, але покишо відключу його
        
        self.failure_reason=None
        self.result=None
        self.skipped_crs_qty=0
        self.unit_filtered_crs_qty=0
        self.max_result_distance=200000
        self.total_crs_to_check=0
        self.processed_crs_qty=0
        self.success_crs_qty=0
        self.failed_crs_qty=0
        self.matched_crs_qty=0
        self.initial_progress=2
        self.center_progress_weight=8
        self.crs_progress_weight=89
        
        self.message=''
        
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
        
        
        self.total_result={} #словник в форматі [назва шару : {чи шар перевірений, вірогідна ск, помилка, інші можливі СК з відстанями до них}
        main_crs=QgsCoordinateReferenceSystem('EPSG:3857')
        self.transformContext = QgsCoordinateTransformContext()#project.transformContext() мало брати з перетворень які заьиті як стандртні в проекті...але на 3.22 не працює
        
        for key, value in self.proj_list.items():
            crs=QgsCoordinateReferenceSystem(key)
            self.transformContext.addCoordinateOperation(crs,main_crs,value)
        #self.transformContext.readSettings()
        #self.message=''+str(self.transformContext.coordinateOperations())
    
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


    def getFailure(self):
        return self.failure_reason

    def emit_stats(self):
        self.statsChanged.emit(
            self.total_crs_to_check,
            self.processed_crs_qty,
            self.success_crs_qty,
            self.failed_crs_qty,
            self.matched_crs_qty
        )
    
    def run(self):
        try:
            self.setProgress(self.initial_progress)
            self.message=self.message+f'СК проекту: {self.canvas_crs.authid()}\r\n'
            self.message=self.message+f'Точка кліку: {self.click_point.toString(4)}\r\n'
            for layer in self.layers:
                layer_id=layer.id()
                self.message=self.message+f'\r\nПеревіряємо шар: {layer.name()}\r\n*************************************************************\r'

                self.total_result[layer_id]={}
                self.total_result[layer_id]['LayerName']=layer.name()
                self.total_result[layer_id]['Checked']=True #відмічаємо шо шар провірявся

                CRS_list = None
                centroid=self.find_center(layer) #Визначаємо центроїд шару
                if self.isCanceled():
                    self.failure_reason='Підбір СК відмінено користувачем'
                    return False
                if centroid:
                    self.message=self.message+f'Центроїд шару: {centroid.toString(4)}\r\n===============================================================\r\n'
                    CRS_list=self.range_distances(layer, centroid, self.click_point) #Отримуємо список з пар (СК, відстаь до точки кліку в цій СК)
                    if self.isCanceled():
                        self.failure_reason='Підбір СК відмінено користувачем'
                        return False
                else:
                    self.message=self.message+'Центроїд шару не визначено\r\n===============================================================\r\n'
                    self.total_result[layer_id]['Error']=self.failure_reason
                if CRS_list:
                    found_crs=CRS_list[0][3]

                    self.total_result[layer_id]['FoundCRS']=found_crs
                    self.total_result[layer_id]['PossibleCRS']=self.format_crs_result(CRS_list[0]) #Головна СК
                    if len(CRS_list)>1:
                        possible_crs = '\r\n'.join([self.format_crs_result(result) for result in CRS_list[1:]])

                        self.total_result[layer_id]['OtherPossibleCRS'] = f'\r\n\tІнші можливі СК:\r\n {possible_crs}' #Інші СК
                    else:
                        self.total_result[layer_id]['OtherPossibleCRS']=''
                else:
                    self.total_result[layer_id]['Error']=self.failure_reason
            if self.total_result:
                self.setProgress(100)
                return True
            else:
                if not self.failure_reason:
                    self.failure_reason='Помилка підбору СК для шарів'
                return False
        except Exception as e:
            self.failure_reason=f'Помилка підбору СК: {type(e).__name__}: {str(e)}'
            self.message=self.message+self.failure_reason+'\r\n'
            return False
    
    def crs_from_proj(self, crs):
        try:
            proj_string = crs.toProj()
        except Exception:
            self.skipped_crs_qty=self.skipped_crs_qty+1
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_string:
            self.skipped_crs_qty=self.skipped_crs_qty+1
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
            self.skipped_crs_qty=self.skipped_crs_qty+1
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_created:
            self.skipped_crs_qty=self.skipped_crs_qty+1
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        if not proj_crs.isValid():
            self.skipped_crs_qty=self.skipped_crs_qty+1
            self.failed_crs_qty=self.failed_crs_qty+1
            return None

        return proj_crs

    def format_crs_result(self, crs_result):
        crs_code, crs_name, distance = crs_result[0], crs_result[1], crs_result[2]
        return f"{self.format_crs_label(crs_code, crs_name)} - {f'{distance:,.0f}'.replace(',', ' ')} метрів від точки кліку"

    def crs_name(self, crs):
        try:
            return crs.description()
        except Exception:
            return ''

    def format_crs_label(self, crs_code, crs_name):
        if crs_name:
            return f'{crs_code} - {crs_name}'
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

    def should_skip_crs_by_centroid_units(self, crs, centroid):
        try:
            return crs.isGeographic() and not self.centroid_can_be_geographic(centroid)
        except Exception:
            return False

    def range_distances(self, layer, centroid, click_point):
        self.skipped_crs_qty=0
        self.unit_filtered_crs_qty=0
        distance_results=[]
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

            total_crs_qty=len(self.proj_list)+len(srs_ids)
            self.message=self.message+f'Перевіряємо до {total_crs_qty} СК з бази QGIS\r\n'

        if not self.total_crs_to_check:
            self.total_crs_to_check=total_crs_qty*self.layers_qty
            self.emit_stats()

        if total_crs_qty == 0:
            if selected_crs_mode:
                self.failure_reason='В активному наборі СК немає кодів для перевірки'
            else:
                self.failure_reason='У базі QGIS не знайдено валідних СК для перевірки'
            return None

        progress_step=self.crs_progress_weight/total_crs_qty/self.layers_qty

        def process_crs(crs_code, crs, has_custom_operation):
            if self.isCanceled():
                self.failure_reason='Підбір СК відмінено користувачем'
                return False

            try:
                if not crs.isValid():
                    self.skipped_crs_qty=self.skipped_crs_qty+1
                    self.failed_crs_qty=self.failed_crs_qty+1
                    return True

                if self.should_skip_crs_by_centroid_units(crs, centroid):
                    self.skipped_crs_qty=self.skipped_crs_qty+1
                    self.unit_filtered_crs_qty=self.unit_filtered_crs_qty+1
                    self.failed_crs_qty=self.failed_crs_qty+1
                    return True

                real_crs_code = crs.authid() or crs_code
                real_crs_name = self.crs_name(crs)
                if real_crs_code in known_crs:
                    return True

                proj_crs = self.crs_from_proj(crs)
                if not proj_crs:
                    return True

                layer_crs = self.crs_for_layer(crs, real_crs_code)
                known_crs.add(real_crs_code)

                xform = QgsCoordinateTransform(proj_crs, self.canvas_crs, self.transformContext)
                if has_custom_operation:
                    xform.setCoordinateOperation(self.proj_list[crs_code])
                xform.setBallparkTransformsAreAppropriate(True)
                xform.setAllowFallbackTransforms(True)
                #Перетворюємо центроїд шару в СК карти приймаючи вихідну проекцію зі списку
                transformed_centroid = xform.transform(centroid)
                #Вираховуємо відстань від перетвореного центроїду до референсної точки
                distance = click_point.distance(transformed_centroid)                
                int_distance=int(distance)
                self.success_crs_qty=self.success_crs_qty+1
                self.crsChecked.emit(layer.id(), layer.name(), real_crs_code, real_crs_name, int_distance, layer_crs)
                
                #Записуємо результат
                if distance<self.max_result_distance:
                    self.matched_crs_qty=self.matched_crs_qty+1
                    distance_results.append((real_crs_code, real_crs_name, int_distance, layer_crs))
                    self.message=self.message+f'{self.format_crs_label(real_crs_code, real_crs_name)}: {int_distance:,} метрів від точки кліку\r\n'.replace(',',' ')
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
                    if not process_crs(crs_code, crs, crs_code in self.proj_list):
                        return None
                except Exception:
                    self.skipped_crs_qty=self.skipped_crs_qty+1
                    self.failed_crs_qty=self.failed_crs_qty+1

                self.processed_crs_qty=self.processed_crs_qty+1
                self.emit_stats()
                self.setProgress(self.progress()+progress_step)
        else:
            for crs_code in self.proj_list.keys():
                try:
                    crs = QgsCoordinateReferenceSystem(crs_code)
                    if not process_crs(crs_code, crs, True):
                        return None
                except Exception:
                    self.skipped_crs_qty=self.skipped_crs_qty+1
                    self.failed_crs_qty=self.failed_crs_qty+1

                self.processed_crs_qty=self.processed_crs_qty+1
                self.emit_stats()
                self.setProgress(self.progress()+progress_step)

            for srs_id in srs_ids:
                try:
                    crs = QgsCoordinateReferenceSystem.fromSrsId(srs_id)
                    crs_code = crs.authid() or f'QGIS:{crs.srsid()}'
                    if not process_crs(crs_code, crs, False):
                        return None
                except Exception:
                    self.skipped_crs_qty=self.skipped_crs_qty+1
                    self.failed_crs_qty=self.failed_crs_qty+1

                self.processed_crs_qty=self.processed_crs_qty+1
                self.emit_stats()
                self.setProgress(self.progress()+progress_step)
            
        if distance_results:
            if self.skipped_crs_qty:
                self.message=self.message+f'Пропущено СК під час перевірки: {self.skipped_crs_qty}\r\n'
            if self.unit_filtered_crs_qty:
                self.message=self.message+f'З них географічних СК відфільтровано по метричних координатах центроїда: {self.unit_filtered_crs_qty}\r\n'
            result=sorted(distance_results, key=lambda x: x[2])
            return  result #повертаємо відсортовані результати як ліст лістів
        else:
            self.failure_reason="Не вдалося підібрати СК в радіусі 200 км, можливо об'єкти у відносній СК, або мають неправильну геометрію"
            return None 
        
    def find_center(self,layer):
        # if self.simple_search:
            # self.setProgress(self.progress()+self.center_progress_weight/self.layers_qty)
            # extent = layer.extent()
            # geometry = QgsGeometry.fromRect(extent)
            # result = geometry.centroid().asPoint()
            # return result
        
        geometries = []
        featureQTY=layer.featureCount()
        
        progress_step=self.center_progress_weight/featureQTY/self.layers_qty
        
        for feature in layer.getFeatures():
            if self.isCanceled():
                self.failure_reason='Підбір СК відмінено користувачем'
                return None

            if feature.hasGeometry():
                centroid=feature.geometry().makeValid().centroid()
                if not centroid.asWkt()=="Point (0 0)":                    
                    geometries.append(feature.geometry().makeValid().centroid())
            self.setProgress(self.progress()+progress_step)
        
        multipart_geometry = QgsGeometry.collectGeometry(geometries)
        if multipart_geometry.isEmpty():
            self.failure_reason="Центроїд не визначено, можливо геометрія об'єктів відсутня"
            return None
        else:
            result = multipart_geometry.centroid().asPoint()
            #self.message=self.message+result+'\r\n'
            return result
            
