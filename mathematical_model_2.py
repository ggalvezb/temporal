# from simulacion_2 import Family
import simpy
import pandas as pd
import geopandas as gpd
import numpy as np
from collections import OrderedDict
from collections import Counter
import time
import cplex
from cplex import Cplex
from cplex.exceptions import CplexError
import igraph
import sys
from shapely.geometry import Point 


#Cargo datos
persons_data = pd.read_csv("data/personas_antofagasta.csv")
synthetic_population=pd.read_csv('data/synthetic_population.csv')
synthetic_population.ObjectID=synthetic_population.ObjectID.astype(int)
houses_to_evacuate=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Individual_Houses/House_to_evacuate/Houses_to_evacuate.shp')
houses_to_evacuate.OBJECTID=houses_to_evacuate.OBJECTID.astype(int)
#ID mayor a 2219 en nodos es un edificio!!!!!
people_to_evacuate=synthetic_population.merge(houses_to_evacuate,how='left',left_on='ObjectID',right_on='OBJECTID')
people_to_evacuate=people_to_evacuate.dropna(subset=['OBJECTID'])
# streets=gpd.read_file('data/calles_con_delta_altura/calles_delta_altura.shp')
streets=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Corrected_Road_Network/Antofa_nodes_cut_edges/Antofa_edges.shp')
nodes=gpd.read_file('data/nodos_con_altura/Antofa_nodes_altura.shp')
#ID mayor a 4439 en streets es una calle de edificio!!!!!
home_to_mt_load = np.load('data/caminos/home_to_mt.npy',allow_pickle=True).item()
home_to_bd_load = np.load('data/caminos/home_to_bd.npy',allow_pickle=True).item()
bd_to_mt_load = np.load('data/caminos/bd_to_mt.npy',allow_pickle=True).item()
buildings=gpd.read_file('data/edificios/Edificios_zona_inundacion.shp')
meating_points=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Tsunami/Puntos_Encuentro/Puntos_Encuentro_Antofagasta/puntos_de_encuentro.shp')
nodes_without_buildings=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Corrected_Road_Network/Antofa_nodes_cut_edges/sin_edificios/Antofa_nodes.shp')
family_parameters=pd.read_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\parametros_modelo_matematico\\datos_familia_3.csv",index_col=0)
nodes_without_cut=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Corrected_Road_Network/Antofa_nodes_subset2/Antofa_nodes_subset2.shp')
linea_segura=gpd.read_file("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\parametros_modelo_matematico\\Linea_Segura_Vertices.shp")
linea_segura_distancia=pd.read_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\parametros_modelo_matematico\\distancias_a_linea_seguro.csv")


#Revision de cantidad personas nuevas
# sum(list(family_parameters['num_members']))


#Creacion de grafo
g = igraph.Graph(directed = True)
g.add_vertices(list(nodes.id))
g.add_edges(list(zip(streets.u, streets.v)))
g.es['id']=list(streets['id'])
g.es['length']=list(streets['length'])

#Min distancia de punto a grafo
def min_dist(point, gpd2):
    gpd2['Dist'] = gpd2.apply(lambda row:  point.distance(row.geometry),axis=1)
    geoseries = gpd2.iloc[gpd2['Dist'].idxmin()]
    return geoseries

class Family(object):
    ID=0
    families=[]
    def __init__(self, members,housing,route_to_BD,meating_point,length_route_to_BD,route_to_MP,length_route_to_MP,geometry):
        self.ID=Family.ID
        Family.ID+=1                    
        self.members = members          
        self.housing = housing           
        self.route_to_BD = route_to_BD   
        self.route_to_MP = route_to_MP  
        self.route_lenght_to_MP=length_route_to_MP           
        self.route_lenght_to_BD=length_route_to_BD           
        self.meating_point=meating_point
        self.geometry=geometry

    @staticmethod
    def get_members(element):
        age_list=list(synthetic_population.loc[synthetic_population['House ID']==element].Age)
        sex_list=list(synthetic_population.loc[synthetic_population['House ID']==element].Sex)
        adult=len([l for l in age_list if 18<=l<60])
        young=len([l for l in age_list if 12<=l<18])
        kid=len([l for l in age_list if 0<=l<12])
        old=len([l for l in age_list if 60<=l<150])
        men=len([l for l in sex_list if l==1])
        woman=len([l for l in sex_list if l==2])
        members={'adults':adult,'youngs':young,'kids':kid,'olds':old,'males':men,'women':woman}    
        return members
    
    @staticmethod
    def get_route_length(route):
        route_length=0
        for street in route:
            street_find = next(filter(lambda x: x.ID == street, Street.streets))
            route_length+=street_find.lenght
        return(route_length)    

    @staticmethod
    def get_route(element,house_df):
        object_id=str(int(list(house_df['OBJECTID'])[0]))
        route_to_BD=home_to_bd_load[str(object_id)][0]
        length_route_to_BD=Family.get_route_length(route_to_BD)
        route_to_MP=home_to_mt_load[str(object_id)][0]
        length_route_to_MP=Family.get_route_length(route_to_MP)
        building=int(home_to_bd_load[str(object_id)][1])
        meating_point=(building,'BD')
        return(route_to_BD,meating_point,length_route_to_BD,route_to_MP,length_route_to_MP)

    @classmethod
    def builder_families(cls):
        house_id=list(OrderedDict.fromkeys(people_to_evacuate['House ID'])) #list of house_id
        contador=0
        control=0
        for element in house_id:
            members=Family.get_members(element)
            house_df=people_to_evacuate.loc[people_to_evacuate['House ID']==element]
            housing=list(house_df['ObjectID'])[0]
            geometry=list(house_df['geometry'])[0]
            route_to_BD,meating_point,length_route_to_BD,route_to_MP,length_route_to_MP,=Family.get_route(element,house_df)
            Family.families.append(Family(members,housing,route_to_BD,meating_point,length_route_to_BD,route_to_MP,length_route_to_MP,geometry))
            if contador >= control:
                print("Faltan {} familias por construir".format(len(house_id)-contador))
                control+=1000
            contador+=1

    @classmethod
    def reset_class(cls):
        cls.ID=0
        cls.families=[]            

class Street(object):
    streets=[]

    def __init__(self,ID,lenght):
        self.ID=ID
        self.lenght=lenght

    @classmethod
    def builder_streets(cls):
        street_id=list(streets['id'])
        for i in range(len(streets)):
            ID=streets.loc[i]['id']
            lenght=streets.loc[i]['length']
            Street.streets.append(Street(ID,lenght))

class Building(object):
    buildings=[]

    def __init__(self,ID,height,geometry):
        self.ID=ID
        self.height=height
        self.capacity=(height/3)*5
        self.geometry=geometry
    
    @classmethod
    def builder_building(cls):
        for i in range(len(buildings)):
            ID=int(buildings.loc[i].fid)
            height=int(buildings.loc[i].Base.item())
            geometry=buildings.loc[i].geometry
            Building.buildings.append(Building(ID,height,geometry))

class MeatingPoint(object):
    meating_points=[]

    def __init__(self,ID,geometry):
        self.ID=ID 
        self.geometry=geometry

    @classmethod
    def builder_Meatinpoint(cls):
        for i in range(len(meating_points)):
            ID=meating_points.loc[i].OBJECTID
            geometry=meating_points.loc[i].geometry
            MeatingPoint.meating_points.append(MeatingPoint(ID,geometry))    

Street.builder_streets()
print("Termina calles")
Building.builder_building()
MeatingPoint.builder_Meatinpoint()
Family.builder_families()
print("Termina creacion de objetos")


#################################################################
#### -------------------- Modelo Matemático --------------#######
#################################################################

start=time.time()
T_exec=3600

num_personas=0
alerta=0
for familia in Family.families:
    cantidad_personas=familia.members['males']+familia.members['women']
    num_personas+=cantidad_personas
    if cantidad_personas>11:
        # print(cantidad_personas)
        alerta+=1
print(num_personas)


########## ------------ Parámetros de las familias que se usaran en el modelo ------------- ##########
id_fams=[]
olds_fam=[]
kids_fam=[]
adults_fam=[]
num_members=[]
index_fam=[]

contador=0
control=1
for element in Family.families:
    if element.route_lenght_to_BD<element.route_lenght_to_MP:   #Solo si tiene un edifio más cerca que un PE se agregara a las familias para el modelo
        housing_id=element.housing
        dist_min=min(list(linea_segura_distancia.loc[linea_segura_distancia['InputID']==housing_id]['Distance']))
        if dist_min>300: #Solo si supera los 300 mts se incluye en el modelo
            olds_fam.append(element.members['olds'])
            kids_fam.append(element.members['kids'])
            adults_fam.append(element.members['adults'])
            id_fams.append(element.housing)
            num_members.append(element.members['males']+element.members['women'])
            inicio_id=min_dist(element.geometry, nodes_without_buildings)['id']
            index_fam.append(g.vs.find(name=str(inicio_id)).index)
    contador+=1
    if contador>control:
        print("Faltan {} familias por analizar".format(len(Family.families)-contador))
        control+=500
num_families=len(olds_fam)

# #Guardar datos de familia
# dictionary={"id_fams":id_fams,"olds_fam":olds_fam,"kids_fam":kids_fam,"adults_fam":adults_fam,"num_members":num_members,"index_fam":index_fam}
# df=pd.DataFrame(dictionary)
# df.to_csv("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\parametros_modelo_matematico\\datos_familia_3.csv")



# ###### PARAMETROS CARGADOS EXTERNAMENTE
# id_fams=list(family_parameters["id_fams"])
# olds_fam=list(family_parameters["olds_fam"])
# kids_fam=list(family_parameters["kids_fam"])
# adults_fam=list(family_parameters["adults_fam"])
# num_members=list(family_parameters["num_members"])
# index_fam=list(family_parameters["index_fam"])
# num_families=len(id_fams)



########## ----------------- Parámetros de los edificios ------------------ ###########
id_buildings=[]
cap_bd=[]
index_bd=[]

for element in Building.buildings:
    cap_bd.append(int(element.capacity))
    id_buildings.append(element.ID)
    inicio_id=min_dist(element.geometry, nodes_without_buildings)['id']
    index_bd.append(g.vs.find(name=str(inicio_id)).index)
num_buildings=len(cap_bd)


########## ----------- Parámetros de los puntos de encuentro ------------- ##########
id_meatingpoints=[]
cap_mp=[]
index_mp=[]

for element in MeatingPoint.meating_points:
    cap_mp.append(9999999)
    id_meatingpoints.append(element.ID)
    inicio_id=min_dist(element.geometry, nodes_without_buildings)['id']
    index_mp.append(g.vs.find(name=str(inicio_id)).index)
num_meatingpoints=len(id_meatingpoints)

####### --- Parámetros de distnacias familias a edificios y puntos de encuentro ---- #####
building_distance=g.shortest_paths_dijkstra(source=index_fam,target=index_bd,weights=g.es['length'],mode=igraph.ALL)
meatingpoint_distance=g.shortest_paths_dijkstra(source=index_fam,target=index_mp,weights=g.es['length'],mode=igraph.ALL)




WE=10
WK=5
WA=2
MD_HMBD=600
MD_HMMP=999999

#Esto lo guardo por si tengo que armar una funcion nuevamente
# def Optimizador(WE,WK,WA,MD_HMBD,MD_HMMP):
#     print(ninos_edificios,abuelos_edificios,porcentaje_ocupacion)
#     return(Model,ninos_edificios,abuelos_edificios,porcentaje_ocupacion)
###### ------------------ Variables de decision --------------- ######
Model=cplex.Cplex()
print("Empieza la creacion de variables ")

x_vars = np.array([["x("+str(id_fams[i])+","+str(id_buildings[j])+")"  for j in range(0,num_buildings)] for i in range(0,num_families)])
x_varnames = list(x_vars.flatten())
x_vartypes = ['B']*len(x_varnames)
x_varlb = [0.0]*len(x_varnames)
x_varub = [1.0]*len(x_varnames)
# x_varobj=[(5*olds_fam[i]+3*kids_fam[i]+adults_fam[i])-(building_distance[i][j]/100) for j in range(num_buildings) for i in range(num_families)]
x_varobj=[(WE*olds_fam[i]+WK*kids_fam[i]+WA*adults_fam[i])*(1/(building_distance[i][j]+1)) for j in range(0,num_buildings) for i in range(num_families)]

Model.variables.add(obj = x_varobj, lb = x_varlb, ub = x_varub, types = x_vartypes, names = x_varnames)

y_vars = np.array([["y("+str(id_fams[i])+","+str(id_meatingpoints[k])+")"  for k in range(0,num_meatingpoints)] for i in range(0,num_families)])
y_varnames = list(y_vars.flatten())
y_vartypes = 'B'*len(y_varnames)
y_varlb = [0.0]*len(y_varnames)
y_varub = [1.0]*len(y_varnames)
# y_varobj=[(5*olds_fam[i]+3*kids_fam[i]+adults_fam[i])-(meatingpoint_distance[i][k]/100) for k in range(0,num_meatingpoints) for i in range(num_families)]
y_varobj=[0.0 for k in range(num_meatingpoints) for i in range(num_families)]

Model.variables.add(obj = y_varobj, lb = y_varlb, ub = y_varub, types = y_vartypes, names = y_varnames)

Model.objective.set_sense(Model.objective.sense.maximize)
print("variables listas")

###### ----------- Restricciones ----------- ############

#Asigna a las familias a un solo lugar
for i in range(num_families):
    ind_x=[x_vars[i,j] for j in range(num_buildings)]
    ind_y=[y_vars[i,k] for k in range(num_meatingpoints)]
    ind=ind_x+ind_y
    val_x=[1.0 for j in range(num_buildings)]
    val_y=[1.0 for k in range(num_meatingpoints)]
    val=val_x+val_y
    Model.linear_constraints.add(lin_expr=[cplex.SparsePair(ind = ind, val = val)],
                                senses=['E'],
                                rhs=[1.0])
print("Restriccion 1 lista")

#Respeta las capacidades de los edificios
for j in range(num_buildings):
    ind=[x_vars[i,j] for i in range(num_families)]
    val=[num_members[i] for i in range(num_families)]
    Model.linear_constraints.add(lin_expr=[cplex.SparsePair(ind = ind, val = val)],
                            senses=['L'],
                            rhs=[cap_bd[j]])
print("Restriccion 2 lista")

# #Controla la distancia máxima de familia a edificio
Model.linear_constraints.add(lin_expr = [cplex.SparsePair(ind=[x_vars[i,j]],val=[building_distance[i][j]]) for i in range(num_families) for j in range(num_buildings)], 
                                        senses =['L'for i in range(num_families) for j in range(num_buildings)], 
                                        rhs = [MD_HMBD for i in range(num_families) for j in range(num_buildings)])   
print("Restriccion 3 lista")

# # #Controla la distancia máxima de familia a punto de encuentro
# Model.linear_constraints.add(lin_expr = [cplex.SparsePair(ind=[y_vars[i,k]],val=[meatingpoint_distance[i][k]]) for i in range(num_families) for k in range(num_meatingpoints)], 
#                                         senses =['L'for i in range(num_families) for k in range(num_meatingpoints)], 
#                                         rhs = [MD_HMMP for i in range(num_families) for k in range(num_meatingpoints)])   
# print("Restriccion 4 lista")

######### ----------- Resolucion del modelo ------------- ############
end=time.time()
print("Termina creacion de modelo con tiempo de ",(time.time())-start)

Model.parameters.timelimit.set(float(T_exec))
Model.parameters.workmem.set(9000.0)
print("EMPIEZA SOLVE")
Model.solve()

print("\nObjective Function Value = {}".format(Model.solution.get_objective_value()))



###########################################################
####### --------------- Revision ----------------##########
###########################################################

######--------- Asignacion y distribucion ------- #########
abuelos_edificios,ninos_edificios,abuelos_mp,ninos_mp=0,0,0,0
for i in range(num_families):
    contador_edificios=0
    for j in range(num_buildings):
        if(round(Model.solution.get_values("x("+str(id_fams[i])+","+str(id_buildings[j])+")"))==1.0):
            contador_edificios+=1
            abuelos_edificios+=olds_fam[i]
            ninos_edificios+=kids_fam[i]
            # print("EDIFICIO")
            
    contador_mp=0
    for k in range(num_meatingpoints):
        if(round(Model.solution.get_values("y("+str(id_fams[i])+","+str(id_meatingpoints[k])+")"))==1.0):
            contador_mp+=1
            abuelos_mp+=olds_fam[i]
            ninos_mp+=kids_fam[i]
            # print("mp")
    # print("La familia {} fue asignada {} veces a edificio y {} a mp con {} abuelos y {} niños".format(i,contador_edificios,contador_mp,olds_fam[i],kids_fam[i]))
    if contador_edificios == 0 and contador_mp ==0:
        print("La familias {} no fue asignada".format(i))
print("Hay {} niños y {} abuelos en EDIFICIOS".format(ninos_edificios,abuelos_edificios))
print("Hay {} niños y {} abuelos en mp".format(ninos_mp,abuelos_mp))

###### --------- Capacidad edificios -------#########
capacidad_restante=[]
capacidad_ocupada=[]
for j in range(num_buildings):
    capacidad_edificio=0
    for i in range(num_families):
        if(round(Model.solution.get_values("x("+str(id_fams[i])+","+str(id_buildings[j])+")"))==1.0):
            capacidad_edificio+=num_members[i]
    capacidad_restante.append(cap_bd[j]-capacidad_edificio)
    capacidad_ocupada.append(capacidad_edificio)
    if capacidad_edificio>cap_bd[j]:
        print("En el edificio {} se supera la capacidad con {} y su capacidad es de {}".format(j,capacidad_edificio,cap_bd[j]))
capacidad_no_usada=(sum(capacidad_restante)/num_buildings)
porcentaje_ocupacion=(sum(capacidad_ocupada)*100)/sum(cap_bd)
print("En promedio la capacidad no usada es de {} y el procentaje de ocupacion es {}".format(capacidad_no_usada,porcentaje_ocupacion))


###### ------- Distancia de escape -------- ########
for i in range(num_families):
    for j in range(num_buildings):
        if(round(Model.solution.get_values("x("+str(id_fams[i])+","+str(id_buildings[j])+")"))==1.0):
            if building_distance[i][j]>MD_HMBD:
                print("Familia {} supera distancia maxima a edificio con {}".format(i,building_distance[i][j]))
    for k in range(num_meatingpoints):
        if(round(Model.solution.get_values("y("+str(id_fams[i])+","+str(id_meatingpoints[k])+")"))==1.0):
            if meatingpoint_distance[i][k]>MD_HMMP:
                print("Familia {} supera distancia maxima a mp con {}".format(i,meatingpoint_distance[i][k]))







# #Analisis de sensibilidad#
# WE_list=[5]
# WK_list=[10]
# WA_list=[2]
# MD_HMBD_list=[200]
# MD_HMMP_list=[9999]
# ninos_por_edificio=[]
# abuelos_por_edificio=[]
# ocupacion=[]
# WE_list_final=[]
# WK_list_final=[]
# WA_list_final=[]
# MD_HMBD_list_final=[]
# ninos_edificios_final=0
# abuelos_edificios_final=0
# porcentaje_ocupacion_final=0
# for WE in WE_list:
#     for WK in WK_list:
#         for WA in WA_list:
#             for MD_HMBD in MD_HMBD_list:
#                 print("con WE {}, WK {}, WA {}, MD_HMBD {}".format(WE_list,WK_list,WA_list,MD_HMBD_list))
#                 Model,ninos_edificios_final,abuelos_edificios_final,porcentaje_ocupacion_final=Optimizador(WE,WK,WA,MD_HMBD,MD_HMMP)
#                 ninos_por_edificio.append(ninos_edificios_final)
#                 abuelos_por_edificio.append(abuelos_edificios_final)
#                 ocupacion.append(porcentaje_ocupacion_final)
#                 WE_list_final.append(WE)
#                 WK_list_final.append(WK)
#                 WA_list_final.append(WA)
#                 MD_HMBD_list_final.append(MD_HMBD)
# diccionario_resultados={'WE':WE_list_final,'WK':WK_list_final,'WA':WA_list_final,'Max Distance Home to Building':MD_HMBD_list_final,'Occupation':ocupacion,'Numbers of Kids':ninos_por_edificio,'Numbers of Elders':abuelos_por_edificio}
# df_resultados = pd.DataFrame.from_dict(diccionario_resultados)






#################################################################
#### ------------ Creador shape dispersion ---------------#######
#################################################################
houses_to_evacuate=gpd.read_file('C:/Users/ggalv/OneDrive/TESIS MAGISTER/tsunami/Shapefiles/Individual_Houses/House_to_evacuate/Houses_to_evacuate.shp')

dispersion_df=pd.DataFrame(columns=['ID','X','Y','Evacuacion','geometry'])
for i in range(num_families):
    for j in range(num_buildings):
        if(round(Model.solution.get_values("x("+str(id_fams[i])+","+str(id_buildings[j])+")"))==1.0):
            object_id=houses_to_evacuate.loc[houses_to_evacuate['OBJECTID']==float(id_fams[i])]
            dispersion_df=dispersion_df.append({"ID":object_id.OBJECTID.item(),"X":object_id.LATITUD.item(),"Y":object_id.LONGITUD.item(),"Evacuacion":1,'geometry':object_id.geometry.item()},ignore_index=True)
        # else:
        #     object_id=houses_to_evacuate.loc[houses_to_evacuate['OBJECTID']==float(id_fams[i])]
        #     dispersion_df=dispersion_df.append({"ID":object_id.OBJECTID.item(),"X":object_id.LATITUD.item(),"Y":object_id.LONGITUD.item(),"Evacuacion":0,'geometry':object_id.geometry.item()},ignore_index=True)
crs = {'init': 'epsg:5361'}
dispersion_gdf=gpd.GeoDataFrame(dispersion_df, crs=crs)

dispersion_gdf.to_file("C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados_modelo_matematico\\shape_dist_ninos\\dist_ninos_edificios_new.shp")




#################################################################
#### ---------------- Creacion de rutas ------------------#######
#################################################################


path={}
contador=0
control=1
familias=num_families
for i in range(num_families):
    #Saco las ruta si la familia fue asignada a un edificio
    for j in range(0,num_buildings):
        if(round(Model.solution.get_values("x("+str(id_fams[i])+","+str(id_buildings[j])+")"))==1.0):
            family_find = next(filter(lambda x: x.housing == id_fams[i], Family.families))
            building_find=next(filter(lambda x: x.ID==id_buildings[j],Building.buildings))
            inicio_id=min_dist(family_find.geometry, nodes_without_buildings)['id']
            inicio_vertex=g.vs.find(name=str(inicio_id)).index
            try:
                fin_id_bd=min_dist(building_find.geometry.item(), nodes)['id']
            except:
                fin_id_bd=min_dist(building_find.geometry, nodes)['id'] 
            fin_vertex_bd=g.vs.find(name=str(fin_id_bd)).index
            shortest_path=g.get_shortest_paths(inicio_vertex, to=fin_vertex_bd, weights=g.es['length'], mode=igraph.ALL, output="epath")[0]
            path_id=[]
            for z in range(len(shortest_path)):
                path_id.append(g.es[shortest_path[z]]['id'])
            path[id_fams[i]]=[path_id,id_buildings[j]]
        contador+=1
        if contador>control:
            print("Faltan {} familias".format(familias-contador))
            control+=1000

    # #Saco las ruta si la familia fue asignada a un punto de encuentro
    # for k in range(0,num_meatingpoints):
    #     if(round(Model.solution.get_values("y("+str(id_fams[i])+","+str(id_meatingpoints[k])+")"))==1.0):
    #         family_find = next(filter(lambda x: x.housing == id_fams[i], Family.families))
    #         meating_points_find=next(filter(lambda x: x.ID==id_meatingpoints[k],MeatingPoint.meating_points))
    #         inicio_id=min_dist(family_find.geometry, nodes_without_buildings)['id']
    #         inicio_vertex=g.vs.find(name=str(inicio_id)).index
    #         try:
    #             fin_id_bd=min_dist(meating_points_find.geometry.item(), nodes)['id']
    #         except:
    #             fin_id_bd=min_dist(meating_points_find.geometry, nodes)['id'] 
    #         fin_vertex_bd=g.vs.find(name=str(fin_id_bd)).index
    #         shortest_path=g.get_shortest_paths(inicio_vertex, to=fin_vertex_bd, weights=g.es['length'], mode=igraph.ALL, output="epath")[0]
    #         path_id=[]
    #         for z in range(len(shortest_path)):
    #             path_id.append(g.es[shortest_path[z]]['id'])
    #         path[id_fams[i]]=[path_id,id_meatingpoints[k]]
#Guardar diccionario
np.save('C:\\Users\\ggalv\\OneDrive\\TESIS MAGISTER\\Simulacion-evacuacion-antofagasta\\resultados_modelo_matematico\\scape_route_optimal_ninos_primero_23_07.npy', path)


