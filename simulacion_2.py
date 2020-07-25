import itertools
import pandas as pd
from collections import OrderedDict
from collections import Counter
import numpy as np
from numpy.random import RandomState
import simpy
import sys
import time   #Para probar los tiempos de ejecucion
import os
import json

#Para el modelo de optimizacion
import cplex
from cplex import Cplex
from cplex.exceptions import CplexError

#Para paralelizar
# from sklearn.externals.joblib import Parallel, delayed
import multiprocessing as mp

#Para crear grafos y obtener camino minimo
import igraph

#Para geodataframe
import geopandas as gpd
from shapely.geometry import Point
import fiona

inicio=time.time()
class Family(object):
    ID=0
    families=[]
    family_statistics=[]
    family_statistics_dataframe=pd.DataFrame(columns=['ID','Path','Delays','Members','People','Start scape time','End scape time','Evacuation time','x','y','Length scape route','Housing','Safe point'])


    def __init__(self, members, housing, velocity, route,meating_point,scenario,route_lenght,geometry,people_for_stats):
        self.ID=Family.ID
        Family.ID+=1                    
        self.members = members          
        self.housing = housing           
        self.start_scape = None  
        self.velocity = velocity                
        self.route = route   
        self.route_lenght=route_lenght           
        self.env=None
        self.meating_point=meating_point
        self.scenario=scenario
        self.geometry=geometry
        self.prob_go_bd=None
        self.prob_go_mt=None
        self.route_to_bd=None 
        self.route_to_mt=None 
        self.length_route_to_bd=None 
        self.length_route_to_mt=None 
        self.point_mt=None
        self.point_bd=None

        #Stats
        self.family_stats={}
        self.path=[]
        self.path_time=[]
        self.path_velocity=[]
        self.delays=0
        self.people=people_for_stats
        self.evacuation_time=0
        self.start_scape_simtime=0
        self.end_scape_simtime=0
        self.end_point=None
        self.dem_info=None
        

    @staticmethod
    def get_members(element):
        age_list=list(synthetic_population.loc[synthetic_population['House ID']==element].Age)
        sex_list=list(synthetic_population.loc[synthetic_population['House ID']==element].Sex)
        people_for_stats=[{'Age':x,'Sex':y}for (x,y) in zip(age_list,sex_list)]
        adult=len([l for l in age_list if 18<=l<60])
        young=len([l for l in age_list if 12<=l<18])
        kid=len([l for l in age_list if 0<=l<12])
        old=len([l for l in age_list if 60<=l<150])
        men=len([l for l in sex_list if l==1])
        woman=len([l for l in sex_list if l==2])
        members={'adults':adult,'youngs':young,'kids':kid,'olds':old,'males':men,'women':woman}    
        return members,people_for_stats

    @staticmethod
    def get_route_length(route):
        route_length=0
        for street in route:
            street_find = next(filter(lambda x: x.ID == street, Street.streets))
            route_length+=street_find.lenght
        return(route_length)    

    @staticmethod
    def get_route(type_road,scenario,house_df):
        if scenario=='scenario 1':
            prob_go_bd,prob_go_mt,route_to_mt,route_to_bd,length_route_to_bd,length_route_to_mt,point_mt,point_bd=None,None,None,None,None,None,None,None
            object_id=str(int(list(house_df['OBJECTID'])[0]))
            route=type_road[str(object_id)][0].copy()
            length_route=Family.get_route_length(route)
            meating_point=(int(type_road[str(object_id)][1]),'MP')

        elif scenario=='scenario 2':
            object_id=str(int(list(house_df['OBJECTID'])[0]))
            route_to_mt=home_to_mt_load[str(object_id)][0]
            length_route_to_mt=Family.get_route_length(route_to_mt)
            meating_point=int(home_to_mt_load[str(object_id)][1])
            point_mt=meating_point
            route_to_bd=home_to_bd_load[str(object_id)][0]
            length_route_to_bd=Family.get_route_length(route_to_bd)
            building=int(home_to_bd_load[str(object_id)][1])
            point_bd=building
            prob_go_bd=length_route_to_mt/(length_route_to_mt+length_route_to_bd)
            prob_go_mt=length_route_to_bd/(length_route_to_mt+length_route_to_bd)
            if prob_go_bd>=0.85:
                route=route_to_bd
                meating_point=(building,'BD')
                length_route=length_route_to_bd
            elif prob_go_mt>=0.85:
                route=route_to_mt
                meating_point=(meating_point,'MP')
                length_route=length_route_to_mt
            else:
                route=np.random.choice(2,p=[prob_go_mt,prob_go_bd])
                if route==0: route=route_to_mt
                else: route=route_to_bd
                # route=np.random.choice(route_to_mt,route_to_bd,p=[prob_go_mt,prob_go_bd])
                if route==route_to_mt:
                    meating_point=(meating_point,'MP')
                    length_route=length_route_to_mt 
                elif route==route_to_bd:
                    meating_point=(building,'BD')
                    length_route=length_route_to_bd

        elif scenario=='scenario 3':
            prob_go_bd,prob_go_mt,route_to_mt,route_to_bd,length_route_to_bd,length_route_to_mt,point_mt,point_bd=None,None,None,None,None,None,None,None
            object_id=str(int(list(house_df['OBJECTID'])[0]))
            if int(object_id) in optimal_scape.keys():
                route=optimal_scape[int(object_id)][0]
                length_route=Family.get_route_length(route)
                building=int(optimal_scape[int(object_id)][1])
                if int(optimal_scape[int(object_id)][1])<150:
                    meating_point=(building,'BD')
                else:
                    meating_point=(building,'MP')
            else: #esto me lo agradeceras en el futuro
                route=home_to_mt_load[str(object_id)][0]
                length_route=Family.get_route_length(route)
                building=int(home_to_mt_load[str(object_id)][1])
                meating_point=(building,'MP')
        return(route,meating_point,length_route,prob_go_bd,prob_go_mt,route_to_bd,route_to_mt,length_route_to_bd,length_route_to_mt,point_mt,point_bd)
  
    @staticmethod
    def get_velocity(members):
        kids=members['kids']
        adults=members['adults']+members['youngs']
        olds=members['olds']
        total_person=kids+adults+olds
        velocity=((kids*1.3)+(adults*1.5)+(olds*0.948))/total_person
        return(velocity)

    def streets_statistics(self,id_to_search,velocity,time):
        # street_dict={'ID':id_to_search,'Velocity':velocity}
        street_dict=id_to_search
        self.evacuation_time+=time
        self.path.append(street_dict)
        self.path_time.append(time)
        self.path_velocity.append(velocity)

    def save_stats(self):
        self.family_stats['ID']=self.ID
        self.family_stats['Path']=self.path
        self.family_stats['Path Time']=self.path_time
        self.family_stats['Path Velocity']=self.path_velocity
        self.family_stats['Delays']=self.delays
        self.family_stats['Members']=self.members
        self.family_stats['People']=self.people
        self.family_stats['Start scape time']=self.start_scape_simtime*60
        self.family_stats['End scape time']=self.end_scape_simtime
        self.family_stats['Evacuation time']=self.evacuation_time
        self.family_stats['x']=self.geometry.x
        self.family_stats['y']=self.geometry.y
        self.family_stats['Length scape route']=self.route_lenght
        self.family_stats['Housing']=self.housing
        self.family_stats['Safe point']=self.meating_point
        Family.family_statistics_dataframe=Family.family_statistics_dataframe.append({'ID':self.ID,'Path':self.path,'Path Time':self.path_time,'Path Velocity':self.path_velocity,'Delays':self.delays.astype(float),'Members':self.members,'People':self.people,'Start scape time':self.start_scape_simtime.astype(float),'End scape time':self.end_scape_simtime,'Evacuation time':self.evacuation_time,'x':self.geometry.x,'y':self.geometry.y,'Length scape route':self.route_lenght,'Housing':self.housing,'Safe point':self.meating_point},ignore_index=True)
        Family.family_statistics.append(self.family_stats)

    @classmethod
    def builder_families(cls,type_road,scenario):
        house_id=list(OrderedDict.fromkeys(people_to_evacuate['House ID'])) #list of house_id
        start=time.time()
        for element in house_id:
            members,people_for_stats=Family.get_members(element)
            house_df=people_to_evacuate.loc[people_to_evacuate['House ID']==element]
            housing=list(house_df['ObjectID'])[0]
            geometry=list(house_df['geometry'])[0]
            route,meating_point,length_route,prob_go_bd,prob_go_mt,route_to_bd,route_to_mt,length_route_to_bd,length_route_to_mt,point_mt,point_bd=Family.get_route(type_road,scenario,house_df)
            velocity=Family.get_velocity(members)
            Family.families.append(Family(members,housing,velocity,route,meating_point,scenario,length_route,geometry,people_for_stats))
            if scenario=='scenario 2':
                Family.families[-1].prob_go_bd=prob_go_bd
                Family.families[-1].prob_go_mt=prob_go_mt
                Family.families[-1].route_to_bd=route_to_bd
                Family.families[-1].route_to_mt=route_to_mt
                Family.families[-1].length_route_to_bd=length_route_to_bd
                Family.families[-1].length_route_to_mt=length_route_to_mt
                Family.families[-1].point_mt=point_mt
                Family.families[-1].point_bd=point_bd

        print("fin construir familias ", (time.time())-start)



    def evacuate(self):
        route_copy=self.route.copy()
        ################
        # Salen de sus casas
        ################
        time_1=300
        self.delays=self.start_scape
        self.start_scape_simtime=self.start_scape
        yield self.env.timeout(self.start_scape*60)  
        while True:
            ################
            # Inician una calle
            ################
            if len(route_copy)!=0:
                id_to_search=route_copy.pop(0)
                street_find = next(filter(lambda x: x.ID == id_to_search, Street.streets))
                street_find.flow+=1
                if street_find.max_flow<street_find.flow: street_find.max_flow=street_find.flow #Actualizo el maimo flujo por calle
                if street_find.flow>street_find.capacity: street_find.velocity=0.751 
                velocity=min(street_find.velocity,self.velocity)
                # print("Velocidad en m/s: ",velocity)
                # print("Largo de calle: ",street_find.lenght)
                # print("Tiempo de viaje en la calle: ",(street_find.lenght/velocity))
                Family.streets_statistics(self,id_to_search,velocity,street_find.lenght/velocity)
                yield self.env.timeout(street_find.lenght/velocity)
                street_find.flow-=1
                # print("WENAAA ",self.env.now)

                if Model.replica==1:
                    if self.env.now>Colect_streets_stats.time: #Actualizo y guardo flujo en calles
                        Colect_streets_stats.update_steetsdf_stats(self.scenario)
                        Colect_streets_stats.time+=60

            if len(route_copy)==0: #Final de ruta
                try:
                    if self.meating_point[1]=='MP': #Llega a punto de encuentro
                        print('FAMILIA  '+str(self.ID)+' TERMINA EVACUACIÓN Y LLEGAN A PUNTO DE ENCUENTRO '+str(self.meating_point)+'EN TIEMPO '+str(self.env.now))
                        id_to_search=self.meating_point[0]    
                        meatingpoint_find = next(filter(lambda x: x.ID == id_to_search, MeatingPoint.meating_points))
                        new_members=dict(Counter(meatingpoint_find.members)+Counter(self.members))
                        meatingpoint_find.members=new_members
                        meatingpoint_find.persons+=self.members['males']+self.members['women']
                        self.end_scape_simtime=self.env.now #Guardo tiempo en que arriba a punto seguro
                        Family.save_stats(self)#Guardo estadisticas
                        break
                except:
                    print("Error en familia {} con punto de encuentro {}".format(self.ID,self.meating_point))
                    sys.exit()

                if self.meating_point[1]=='BD': #Llega a edificio
                    id_to_search=self.meating_point[0]
                    building_search=next(filter(lambda x: x.ID == id_to_search, Building.buildings))
                    print('FAMILIA '+str(self.ID)+' LLEGAN A EDIFICO '+str(building_search.ID)+' Y ESTE SE ENCUENTRA '+str(building_search.state)+' EN TIEMPO '+str(self.env.now))
                    if building_search.state == 'open':
                        building_search.num_family+=1
                        building_search.capacity-=self.members['males']+self.members['women']
                        new_members=dict(Counter(building_search.members)+Counter(self.members))
                        building_search.members=new_members
                        self.end_scape_simtime=self.env.now #Guardo tiempo en que arriba a punto seguro
                        Family.save_stats(self)#Guardo estadisticas
                        if building_search.capacity<=0: building_search.state='close'
                    else:
                        ##########
                        # Si el edificio esta cerrado se van a un punto de encuentro
                        ##########
                        try:
                            if self.scenario=='scenario 2':
                                route_copy=bd_to_mt_load[str(self.housing)][0].copy()
                                self.meating_point=bd_to_mt_load[str(self.housing)][1]
                            elif self.scenario=='scenario 3':
                                route_copy=bd_to_mt_load[str(self.housing)][0].copy()
                                print("ESTA EN EDIFICIO QUE NO DEBERIA ESTAR")
                                sys.exit()
                        except:
                            print("Error en familia {} con cada {}".format(self.ID,self.housing))
                            sys.exit()

            
                        while True:
                            ##########
                            # Vuelven a calle
                            ##########
                            id_to_search=route_copy.pop(0)
                            street_find = next(filter(lambda x: x.ID == id_to_search, Street.streets))
                            street_find.flow+=1
                            if street_find.max_flow<street_find.flow: street_find.max_flow=street_find.flow #Actualizo el maximo flujo por calle
                            if street_find.flow>street_find.capacity: street_find.velocity=0.751 
                            velocity=min(street_find.velocity,self.velocity)
                            Family.streets_statistics(self,id_to_search,velocity,street_find.lenght/velocity)
                            yield self.env.timeout(street_find.lenght/velocity)
                            street_find.flow-=1
                            if len(route_copy)==0:
                                ###########
                                # Llegan a un punto de encuentro
                                ###########
                                print('FAMILIA  '+str(self.ID)+' TERMINA EVACUACIÓN Y LLEGAN A PUNTO DE ENCUENTRO '+str(self.meating_point)+' EN TIEMPO '+str(self.env.now))
                                id_to_search=self.meating_point    
                                meatingpoint_find = next(filter(lambda x: x.ID == id_to_search, MeatingPoint.meating_points))
                                new_members=dict(Counter(meatingpoint_find.members)+Counter(self.members))
                                meatingpoint_find.members=new_members
                                meatingpoint_find.persons+=self.members['males']+self.members['women']
                                self.end_scape_simtime=self.env.now #Guardo tiempo en que arriba a punto seguro
                                Family.save_stats(self)#Guardo estadisticas
                                break
                    break

class Street(object):
    streets=[]

    def __init__(self,ID,height,type_street,lenght,capacity,velocity,geometry):
        self.ID=ID
        self.flow=0
        self.velocity=velocity
        self.height=height
        self.type=type_street
        self.lenght=lenght
        self.capacity=int(capacity)  #Si se supera este valor se considera atochado y la calle baja su velocidad a 0.751 m/s
        self.max_flow=0
        self.geometry=geometry

    @staticmethod
    def get_capacity(type_street,lenght):
        if type_street=='residential': width=4 
        elif type_street=='primary': width=8
        elif type_street=='tertiary': width=2
        else: width=4
        area=width*lenght
        return(area*1.55)  #Se considera que con 1.55 personas por m2 se puede transitar libremente

    @staticmethod
    def get_velocity(height,lenght):
        pendiente=(height/lenght)*100
        if pendiente<=5.6: velocity=999999
        elif 5.6<pendiente<=8: velocity=0.91
        elif 8<pendiente<=11.2: velocity=0.76
        elif 11.2<pendiente<=14: velocity=0.60
        elif 14<pendiente<=30: velocity=0.31
        elif 30<pendiente: velocity=0.2
        else:
            velocity=999999
        return(velocity)

    @classmethod
    def builder_streets(cls):
        street_id=list(streets['id'])
        contador=0
        control=1000
        for i in range(len(streets)):
            ID=streets.loc[i]['id']
            height=streets.loc[i]['height']
            type_street=streets.loc[i]['highway']
            lenght=streets.loc[i]['length']
            geometry=streets.loc[i]['geometry']
            capacity=Street.get_capacity(type_street,lenght)
            velocity=Street.get_velocity(height,lenght)
            Street.streets.append(Street(ID,height,type_street,lenght,capacity,velocity,geometry))
            contador+=1
            if contador==control:
                print("Faltan "+str(len(street_id)-contador)+' para que empiece la simulacion')
                control+=1000

class Building(object):
    buildings=[]

    def __init__(self,ID,height,geometry):
        self.ID=ID
        self.height=height
        self.capacity=(height/3)*5
        self.num_family=0 
        self.state='open'
        self.geometry=geometry
        self.x=geometry.x
        self.y=geometry.y
        self.members={'adults':0,'youngs':0,'kids':0,'olds':0,'males':0,'women':0}

    
    @classmethod
    def builder_building(cls):
        for element in buildings['fid']:
            ID=int(element)
            building=buildings.loc[buildings['fid']==element]
            height=int(building['Base'].item())
            geometry=building['geometry'].item()
            Building.buildings.append(Building(ID,height,geometry))
     
class MeatingPoint(object):
    meating_points=[]

    def __init__(self,ID):
        self.ID=ID 
        self.members={'adults':0,'youngs':0,'kids':0,'olds':0,'males':0,'women':0}
        self.persons=0

    @classmethod
    def builder_Meatinpoint(cls):
        for i in range(len(meating_points)):
            ID=meating_points.loc[i].OBJECTID
            MeatingPoint.meating_points.append(MeatingPoint(ID))

class Colect_streets_stats(object):
    streets_df=pd.DataFrame()
    time=10

    def setup_colects_street():
        Colect_streets_stats.streets_df['ID']=[element.ID for element in Street.streets]
        Colect_streets_stats.streets_df['geometry']=[element.geometry for element in Street.streets]
        Colect_streets_stats.streets_df['Flow']=[element.flow for element in Street.streets]
        Colect_streets_stats.streets_df['Max Flow']=[element.max_flow for element in Street.streets]


    def update_steetsdf_stats(scenario):
        Colect_streets_stats.streets_df['Flow']=[element.flow for element in Street.streets]
        Colect_streets_stats.streets_df['Max Flow']=[element.max_flow for element in Street.streets]
        crs = {'init': 'epsg:5361'}
        streets_gdf=gpd.GeoDataFrame(Colect_streets_stats.streets_df,crs=crs)
        streets_gdf.to_file("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\calles\\calles de escenario {} replica {} tiempo {}.shp".format(scenario,Model.replica,Colect_streets_stats.time))

class Streams(object):
    def __init__(self,startscape_seed):
        self.startscape_rand=RandomState()
        self.startscape_rand.seed(startscape_seed)
    ##esta funcion hace que todos los delays sena cero
    # def generate_startscape_rand(self,members):
    #     if members['kids']==0 and members['olds']==0:            
    #         stratscape_vals=np.arange(1)
    #         startscape_prob=[1]
    #     elif members['kids']>0 and members['olds']==0:            
    #         stratscape_vals=np.arange(1)
    #         startscape_prob=[1]  
    #     elif members['kids']==0 and members['olds']>0:            
    #         stratscape_vals=np.arange(1)
    #         startscape_prob=[1]  
    #     else:            
    #         stratscape_vals=np.arange(1)
    #         startscape_prob=[1]                  
    #     return(self.startscape_rand.choice(stratscape_vals,p=startscape_prob)) 

    #esta funcion hace que todos los delays sean segun una funcion de dist
    def generate_startscape_rand(self,members):
        if members['kids']==0 and members['olds']==0:            
            stratscape_vals=np.arange(2,10)
            startscape_prob= (0.2,0.3,0.3,0.15,0.05,0.0,0.0,0.0)
        elif members['kids']>0 and members['olds']==0:            
            stratscape_vals=np.arange(2,10)
            startscape_prob= (0.0,0.1,0.15,0.30,0.3,0.15,0.0,0.0)  
        elif members['kids']==0 and members['olds']>0:            
            stratscape_vals=np.arange(2,10)
            startscape_prob= (0.0,0.0,0.0,0.1,0.3,0.3,0.15,0.15)  
        else:            
            stratscape_vals=np.arange(2,10)
            startscape_prob= (0.0,0.0,0.0,0.0,0.2,0.3,0.3,0.2)                  
        return(self.startscape_rand.choice(stratscape_vals,p=startscape_prob))   

class Model(object):
    replica=1
    def __init__(self, seeds,scenario,simulation_time):
        self.startscape_seed=seeds
        print("seed 2: ",self.startscape_seed)
        self.simulation_time=simulation_time
        self.scenario=scenario

    @staticmethod
    def get_route(family,prob_go_mt,prob_go_bd,route_to_bd,route_to_mt,length_route_to_bd,length_route_to_mt):
        print(prob_go_bd)
        if prob_go_bd>=0.85:
            family.route=route_to_bd
            family.meating_point=(family.point_bd,'BD')
            family.length_route=length_route_to_bd
        elif prob_go_mt>=0.85:
            family.route=route_to_mt
            family.meating_point=(family.point_mt,'MP')
            family.length_route=length_route_to_mt
        else: 
            route=np.random.choice(2,p=[prob_go_mt,prob_go_bd])
            if route==0: route=route_to_mt
            else: route=route_to_bd
            # route=np.random.choice([route_to_mt,route_to_bd],p=[prob_go_mt,prob_go_bd])
            if route==route_to_mt:
                family.route=route_to_mt
                family.meating_point=(family.point_mt,'MP')
                family.length_route=length_route_to_mt 
            elif route==route_to_bd:
                family.route=route_to_bd
                family.meating_point=(family.point_bd,'BD')
                family.length_route=length_route_to_bd


    def run(self,scenario):

        Family.family_statistics=[]
        S = Streams(self.startscape_seed)
        env=simpy.Environment()
        #Acá reinicio lo que se debe reiniciar para una nueva iteracion
        for family in Family.families:
            family.evacuation_time=0
            family.start_scape=S.generate_startscape_rand(family.members) #Vario el tiempo inicial de escape
            family.path=[]
            family.path_time=[]
            family.path_velocity=[]
            if scenario=='scenario 2': Model.get_route(family,family.prob_go_mt,family.prob_go_bd,family.route_to_bd,family.route_to_mt,family.length_route_to_bd,family.length_route_to_mt) #Vario la ruta de escape
            family.env=env
            family.env.process(family.evacuate())

        for building in Building.buildings:
            building.capacity=(building.height/3)*5
            building.num_family=0 
            building.state='open'
        
        for mp in MeatingPoint.meating_points:
            mp.members={'adults':0,'youngs':0,'kids':0,'olds':0,'males':0,'women':0}
            mp.persons=0

        env.run()
        #Aca se acaba la replica, entonces de aqui debo rescatar las estadisticas de la corrida
        Family.family_statistics_dataframe.to_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica+rep_inicio)+" Family.csv")
        Family.family_statistics_dataframe=pd.DataFrame(columns=['ID','Path','Delays','Members','People','Start scape time','End scape time','Evacuation time','x','y','Length scape route','Housing','Safe point']) #Esto reinicia el dataframe para que no ocupe memoria


        MP_statistics_dataframe=pd.DataFrame(columns=['ID','Members','Persons'])
        for element in MeatingPoint.meating_points:
            MP_statistics_dataframe=MP_statistics_dataframe.append({'ID':element.ID.astype(str),'Members':element.members,'Persons':element.persons},ignore_index=True)
        MP_statistics_dataframe.to_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica+rep_inicio)+" MP.csv")

        BD_statistics_dataframe=pd.DataFrame(columns=['ID','Members','Num Family','x','y'])
        for element in Building.buildings:
            BD_statistics_dataframe=BD_statistics_dataframe.append({'ID':element.ID,'Members':element.members,'Num Family':element.num_family,'x':element.x,'y':element.y},ignore_index=True)
        BD_statistics_dataframe.to_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica+rep_inicio)+" BD.csv")

        
        # json_family=json.dumps(Family.family_statistics)
        # with open("C:\\Users\\ggalv\\Google Drive\\Respaldo\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica)+" Family.txt",'w') as f:
        #     f.write(json_family)
        
        # MP_statistics=[{'ID':element.ID.astype(str),'Members':element.members,'Persons':element.persons} for element in MeatingPoint.meating_points]
        # json_MP=json.dumps(MP_statistics)
        # with open("C:\\Users\\ggalv\\Google Drive\\Respaldo\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica)+" MP.txt",'w') as f:
        #     f.write(json_MP)
        
        # BD_statistics=[{'ID':element.ID,'Members':element.members,'Num_families':element.num_family,'Final state':element.state} for element in Building.buildings]
        # # BD_statistics=[{'ID':element.ID,'Members':element.members,'Num_families':element.num_family,'Geolocation':element.geometry,'Final state':element.state} for element in Building.buildings]
        # json_BD=json.dumps(BD_statistics)
        # with open("C:\\Users\\ggalv\\Google Drive\\Respaldo\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\"+str(self.scenario)+" replica "+str(Model.replica)+" BD.txt",'w') as f:
        #     f.write(json_BD)

        Model.replica+=1

class Replicator(object):
    def __init__(self, seeds):
        self.seeds=seeds

    def run(self,params):
        scenario=params[0]
        if scenario=='scenario 1': route_scenario=home_to_mt_load
        elif scenario=='scenario 2': route_scenario=home_to_bd_load
        else: route_scenario=optimal_scape
        Street.builder_streets()
        Building.builder_building()
        MeatingPoint.builder_Meatinpoint()
        print("EMPIEZA CONSTRUCCION DE FAMILIA")
        Family.builder_families(route_scenario,scenario)
        print("LARGO DE FAMILIAS {} DE CALLES {} EDIFICIOS {} Y MP {}".format(len(Family.families),len(Street.streets),len(Building.buildings),len(MeatingPoint.meating_points)))
        Colect_streets_stats.setup_colects_street()

        # return [Model(seeds,*params).run(scenario) for seeds in self.seeds], params
        return [Model(seeds,*params).run(scenario) for seeds in self.seeds]

class Experiment(object):
    def __init__(self,num_replics,scenarios):
        self.seeds = list(zip(*3*[iter([i for i in range(num_replics*3)])]))[rep_inicio:31] #este rango final se cambia para obtener la semillas que uno quiera para la corrida
        self.scenarios = scenarios
    
    def run(self):
        cpu = mp.cpu_count()
        # Parallel(n_jobs=cpu, verbose=5)(delayed(Replicator(self.seeds).run)(scenario) for scenario in self.scenarios)
        for scenario in self.scenarios:
            Replicator(self.seeds).run(scenario)
            # Parallel(n_jobs=cpu, verbose=5)(delayed(Replicator(self.seeds).run(scenario)))
            Family.ID=0
            Family.families=[]
            Street.streets=[]
            Building.buildings=[]
            MeatingPoint.meating_points=[]
            Model.replica=1

if __name__ == '__main__':
    #Cargo datos
    directory=os.getcwd()
    persons_data = pd.read_csv("data/personas_antofagasta.csv")
    synthetic_population=pd.read_csv('data/synthetic_population.csv')
    houses_to_evacuate=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Individual_Houses/House_to_evacuate/Houses_to_evacuate.shp')
    houses_to_evacuate.OBJECTID=houses_to_evacuate.OBJECTID.astype(int)
    #ID mayor a 2219 en nodos es un edificio!!!!!
    people_to_evacuate=synthetic_population.merge(houses_to_evacuate,how='left',left_on='ObjectID',right_on='OBJECTID')
    people_to_evacuate=people_to_evacuate.dropna(subset=['OBJECTID'])
    streets=gpd.read_file('data/calles_con_delta_altura/calles_delta_altura.shp')
    nodes=gpd.read_file('data/nodos_con_altura/Antofa_nodes_altura.shp')
    #ID mayor a 4439 en streets es una calle de edificio!!!!!
    home_to_mt_load = np.load('data/caminos/home_to_mt.npy').item()
    home_to_bd_load = np.load('data/caminos/home_to_bd.npy').item()
    bd_to_mt_load = np.load('data/caminos/bd_to_mt.npy').item()
    optimal_scape=np.load('data/scape_route_optimal.npy').item()
    buildings=gpd.read_file('data/edificios/Edificios_zona_inundacion.shp')
    meating_points=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Tsunami/Puntos_Encuentro/Puntos_Encuentro_Antofagasta/puntos_de_encuentro.shp')
    nodes_without_buildings=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Corrected_Road_Network/Antofa_nodes_cut_edges/sin_edificios/Antofa_nodes.shp')

    time_sim=500
    rep_inicio=0 #aca ingreso el numero de la replic desde la cual quiero obtener las seed
    scenarios=[('scenario 3',time_sim)]
    # scenarios = [('scenario 2',time),('scenario 3',time)]
    # scenarios = [('scenario 1',time),('scenario 2',time),('scenario 3',time_sim)]
    exp = Experiment(1,scenarios)
    exp.run()

final=time.time()
total=final-inicio
print("TERMINO CON TIEMPO ",str(total))
sys.exit()


#######################################
######## REVISION DE REULTADOS ########
#######################################


# class Experiment(object):
#     def __init__(self,num_replics):
#         self.seeds = list(zip(*3*[iter([i for i in range(num_replics*3)])]))[11:31]

# exp = Experiment(30)

# print(exp.seeds)
# print(len(exp.seeds))


edificios_3=pd.read_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\scenario 3 replica 1 BD.csv")
data_escenario3=pd.read_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\scenario 3 replica 1 Family.csv")
data_escenario3=data_escenario3.drop(data_escenario3.index[data_escenario3.loc[data_escenario3['ID']==1956].index.tolist()[0]])
data_escenario3.sort_values(by=['End scape time'])
data_escenario3['Total_persons']=[int(len(i.split(','))/2) for i in data_escenario3['People']]
data_escenario3['Cum_scape'] = data_escenario3['Total_persons'].cumsum()

data_escenario1=pd.read_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados\\prueba_resultados\\resultados_buenos_escenario3_ninos_primero\\scenario 3 replica 1 Family.csv")
data_escenario1=data_escenario1.drop(data_escenario1.index[data_escenario1.loc[data_escenario1['ID']==1956].index.tolist()[0]])
data_escenario1.sort_values(by=['End scape time'])
data_escenario1['Total_persons']=[int(len(i.split(','))/2) for i in data_escenario1['People']]
data_escenario1['Cum_scape'] = data_escenario1['Total_persons'].cumsum()

personas=0
for item,edificio in edificios_3.iterrows():
    personas+=eval(edificio['Members'])['males']+eval(edificio['Members'])['women']
print("Porcentaje de ocupacion:",(personas*100)/9975)

#Cantidades salvadas
import statistics as st
### Obtengo personas salvadas a los 10 minutos ###
tenmin_escenario1_10=max(data_escenario1.loc[(599.9<=data_escenario1['End scape time'])&(data_escenario1['End scape time']<=600.1)]['Cum_scape'])
tenmin_escenario3_10=max(data_escenario3.loc[(599.9<=data_escenario3['End scape time'])&(data_escenario3['End scape time']<=600.1)]['Cum_scape'])
### Obtengo personas salvadas a los 20 minutos ###
tenmin_escenario1_20=max(data_escenario1.loc[(1199.9<=data_escenario1['End scape time'])&(data_escenario1['End scape time']<=1200.1)]['Cum_scape'])
tenmin_escenario3_20=max(data_escenario3.loc[(1199.9<=data_escenario3['End scape time'])&(data_escenario3['End scape time']<=1200.1)]['Cum_scape'])
#promedios de tiempos de evacuacion final
st.mean(list(data_escenario1['End scape time']))/60
st.mean(list(data_escenario3['End scape time']))/60
print((tenmin_escenario1_10*100)/71466,(tenmin_escenario3_10*100)/71466)
print((tenmin_escenario1_20*100)/71466,(tenmin_escenario3_20*100)/71466)


#Transformacion a geodataframe
from geopandas import GeoDataFrame
from shapely.geometry import Point
df=data_escenario3
geometry = [Point(xy) for xy in zip(df.x, df.y)]
gdf = GeoDataFrame(df, crs="EPSG:5361", geometry=geometry)
gdf['BD_ID']=[eval(i)[0] for i in list(gdf['Safe point'])]
gdf.to_file('C:\\Users\\ggalv\\OneDrive\\Desktop\\prueba_modelo_mat_sin_limite\\escenario_3.shp')


#grafico de escape
import math
import matplotlib.pyplot as plt
import seaborn as sns

bins=math.ceil(1+3.322*math.log(len(data_escenario1)))
bins=150
interval=max(max(list(data_escenario1['End scape time']))/bins,max(list(data_escenario3['End scape time']))/bins)
x=[]
y_1=[]
y_2=[]
y_3=[]
under=0
upper=interval
for i in range(bins):
    x.append(under+(interval/2))
    y_1.append(len(data_escenario1.loc[(under<=data_escenario1['End scape time'])&(data_escenario1['End scape time']<upper)]))
    y_3.append(len(data_escenario3.loc[(under<=data_escenario3['End scape time'])&(data_escenario3['End scape time']<upper)]))
    under=upper
    upper+=interval
    # print(data_escenario1.loc[(under<=data_escenario1['End scape time'])&(data_escenario1['End scape time']<upper)])
    # control=input("Enter continuar, 0 para parar")
    # if control == str(0):
    #     sys.exit()

# multiple line plot
plt.figure(figsize=(9,7))
# plt.rcParams["figure.figsize"] = (6,4)
pal = sns.color_palette("Set1")
plt.plot(x, y_1,color=pal[0],alpha=0.8,label='Scenario 3 200mt')
plt.plot(x, y_3,color=pal[2],alpha=0.8,label='Scenario 3 600mt')
plt.legend(loc='upper rigth')
# plt.xlim(0,6000)
# plt.plot([600, 600], [0, 1500], 'k-', lw=0.5)
# plt.ylim(0,3800)
plt.title("Evacuation times")
plt.xlabel("Time(sec)")
plt.ylabel("Quantity of Families")
# plt.savefig('C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Imagenes Para Tesis\\Tiempo_evacuacion_escenarios.png')

 
