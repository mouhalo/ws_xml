import psycopg2
from psycopg2 import sql
from xml.etree import ElementTree as ET
import base64
from typing import Optional
import configparser
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, HTTPException



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Autorise toutes les origines
    allow_credentials=True,
    allow_methods=["*"],  # Autorise toutes les méthodes
    allow_headers=["*"],  # Autorise tous les headers
)

# Charger la configuration de la base de données au démarrage de l'application
def charger_parametres_db(app_name):
    config = configparser.ConfigParser()
    ini_file_path = f"{app_name}.ini"
    config.read(ini_file_path)
    
    db_name     = config.get('GLOBAL', 'DATABASE')
    db_demo     = config.get('GLOBAL', 'BD_DEMO')
    user        = config.get('GLOBAL', 'USER')
    password    = config.get('GLOBAL', 'PASSWORD')
    host        = config.get('GLOBAL', 'SERVEUR')
    port        = config.get('GLOBAL', 'PORT')

    if db_demo:
        db_name = db_demo

    return {
        "dbname": db_name,
        "user": user,
        "password": password,
        "host": host,
        "port": port
    }

def ouvrir_connexion(db_params):
    try:
        return psycopg2.connect(**db_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de connexion à la base de données : {e}")

def executer_requete_sql(conn, sql_query):
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_query)
            conn.commit()
            return cursor.fetchall(), cursor.description
    except psycopg2.Error as e:
        raise HTTPException(status_code=400, detail=f"Erreur lors de l'exécution de la requête SQL : {e}")
    
def rewrite_sql_query(ptable, pecole, pidsite=None, pnum_acteur=None, ptype=None):
    if ptable == 'ecole':
        # Using a parameterized query for safety and readability
        sql_syntax = "SELECT logo FROM etablissement WHERE code_ecole = %s;"
        params = (pecole,)
    else:  # eleve/prof
        sql_syntax = """
            SELECT photo
            FROM t_photo
            WHERE code_ecole = %s
            AND id_site = %s
            AND num_acteur = %s
            AND type_acteur = %s;
        """
        params = (pecole, pidsite, pnum_acteur, ptype)

    return sql_syntax, params  

def ensure_tuple(params):
    if not isinstance(params, tuple):
        return (params,)
    return params


#Point d'entrée GET num_acteur = %1 and id_site = %2 and code_ecole = '%3' and type_acteur = 'E'
@app.get("/api/downloadimagefilter/{app_name}/{ptable}/{pecole}/{pidsite}/{pnum_acteur}/{ptype}")
async def get_photo(app_name: str,ptable: str,pecole: str,pidsite: int,pnum_acteur: int, ptype: str) :
    try:
        # Connexion à la base de données    
       
       db_params = charger_parametres_db(app_name)
       conn = ouvrir_connexion(db_params)
       
       sql, raw_params = rewrite_sql_query(ptable, pecole, pidsite, pnum_acteur, ptype)
       params = ensure_tuple(raw_params)  # Ensure params is a tuple

       cursor = conn.cursor()
       cursor.execute(sql, (params))
       one_photo = cursor.fetchone()
       cursor.close()
       conn.close()

       if not one_photo or not one_photo[0]:
            raise HTTPException(status_code=404, detail="Aucune photo trouvée")

       photo_bytes = one_photo[0]
       photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')

       return {"one_photo": {"photo": photo_base64}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute_requete_from_xml/")
async def traiter_requete(request: Request):
    body = await request.body()
    try:
        xml_req = body.decode('utf-8')
        root = ET.fromstring(xml_req)

        app_name = root.find("application").text
        db_params = charger_parametres_db(app_name)
        sql_query = root.find("requete_sql").text

        if not sql_query or len(sql_query.strip()) <= 5:
            raise HTTPException(status_code=400, detail="Requête SQL invalide ou trop courte.")

        conn = ouvrir_connexion(db_params)
        try:
            data, description = executer_requete_sql(conn, sql_query)

            if not data:
                raise HTTPException(status_code=404, detail="Aucune donnée trouvée.")

            column_names = [desc[0] for desc in description]
            data_json = [{column_names[i]: row[i] for i in range(len(column_names))} for row in data]

            return {"datas": data_json}
        finally:
            conn.close()

    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Erreur lors de l'analyse du XML.")
    except HTTPException as e:
        # Relancer les exceptions HTTPException déjà formatées
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur : {e}")

# Point d'entrée GET XML 
@app.get("/api/execute_sql/{xml_data}")
async def get_datas(xml_data: str) :
    try:
       s_text   = xml_data.replace("*","/")
       # Decode the base64 string
       xml_req  = base64.b64decode(s_text).decode('utf-8')
       #  Format XML Data   
       root = ET.fromstring(xml_req)
       
       def ouvre_param_ini(pnom_file):    
            # Create a ConfigParser object
            config = configparser.ConfigParser()

            # Specify the path to your INI file
            ini_file_path = "%s.ini" % (pnom_file)

            # Read the INI file
            config.read(ini_file_path)

            # Get values from the INI file
            db_name = config.get('GLOBAL', 'DATABASE')
            db_demo = config.get('GLOBAL', 'BD_DEMO')
            user    = config.get('GLOBAL', 'USER')
            password = config.get('GLOBAL', 'PASSWORD')
            host = config.get('GLOBAL', 'SERVEUR')  # Assuming 'SERVEUR' corresponds to 'host' in the dictionary
            port = config.get('GLOBAL', 'PORT')
            if db_demo != "":
                db_name = db_demo
            # Create the dictionary
            database_config = {
            "dbname": db_name,
            "user": user,
            "password": password,
            "host": host,
            "port": port
            }
            return database_config
       app_name = root.find("application").text
       db_params = ouvre_param_ini(app_name)
       # Find sql balise
       sql_syntax = root.find("requete_sql").text
        # Connection on DB
       conn     = psycopg2.connect(**db_params)
       cursor   = conn.cursor()
              
       if len(sql_syntax) <= 5:
        raise HTTPException(status_code=401, detail="aucune syntaxe")
       # Exécution de la requête SQL
       cursor.execute(sql_syntax)
       my_data = cursor.fetchall()
       # Count rows numbers from sql result
       num_columns = len(cursor.description)
       # Connection close
       cursor.close()
       conn.close()
        
       if not my_data:
            raise HTTPException(status_code=404, detail="aucune donnée")
      
       # Build JSON from rows
       column_names = [desc[0] for desc in cursor.description]
       data_json = [{column_names[i]: row[i] for i in range(num_columns)} for row in my_data]
       # Retunr result in json format 
       return {"datas": data_json}
       
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


import json
@app.post("/api/execute_insert_from_xml/")
async def traiter_requete(request: Request):
    body = await request.body()
    try:
        xml_req = body.decode('utf-8')
        root = ET.fromstring(xml_req)

        app_name = root.find("application").text
        json_data = root.find("json_contenu").text
        table_name = root.find("table_name").text
        id_name = root.find("id_name").text
        mode_sql = root.find("mode").text # insert, select, update
        condition = root.find("condition").text
        json_obj = json.loads(json_data)
        
        if mode_sql != "select":
            data = create_entry_post(json_obj, app_name, table_name, id_name, mode_sql,condition)
            if not data :
                raise HTTPException(status_code=404, detail="Aucune donnée trouvée.")
            return  data
        else:
            data, description = create_entry_post(json_obj, app_name, table_name, id_name, mode_sql,condition)
            if not data:
                raise HTTPException(status_code=404, detail="Aucun traitement effectué.")
            
            column_names = [desc[0] for desc in description]
            data_json = [{column_names[i]: row[i] for i in range(len(column_names))} for row in data]
            return data_json
            # {"datas": data_json}
    except ET.ParseError:
            raise HTTPException(status_code=400, detail="Erreur lors de l'analyse du XML.")
    except HTTPException as e:
            # Relancer les exceptions HTTPException déjà formatées
            raise e
    except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur serveur : {e}")

def create_entry_post(json_obj, papp_name, ptable_name, id_name, pmode_sql, pcondition):
    fields = list(json_obj.keys())
    values = list(json_obj.values())

    # Initialize an empty SQL query string
    sql_query = ""

    if pmode_sql == "insert":
        placeholders = ', '.join(['%s'] * len(values))
        sql_query = f"INSERT INTO {ptable_name} ({', '.join(fields)}) VALUES ({placeholders}) RETURNING \"{id_name}\" as id;"
    elif pmode_sql == "update":
        update_assignments = [f"{field} = %s" for field in fields]
        sql_query = f"UPDATE {ptable_name} SET {', '.join(update_assignments)} WHERE {pcondition} RETURNING \"{id_name}\" as id;"
    elif pmode_sql == "delete":
    # Ensure that the condition for deletion is safely constructed.
    # It's crucial to avoid SQL injection by using parameterized queries.
    # The condition is expected to be provided in a safe manner, as it's directly included in the SQL query here.
        sql_query = f"DELETE FROM {ptable_name} WHERE {pcondition} RETURNING \"{id_name}\" as id;"
    # The rest of the operation remains similar to the insert and update operations,
    # but without needing to handle input values for fields, as deletion is condition-based.
    elif pmode_sql == "select":
            # List to hold formatted values
        formatted_values = []
        # Iterate over the values and format them according to their type
        for value in values:
            if isinstance(value, int):
                # Integers can be used directly in SQL
                formatted_values.append(value)
            elif isinstance(value, float):
                # Numeric (floating-point) values can also be used directly
                formatted_values.append(value)
            elif isinstance(value, bool):
                # Booleans in PostgreSQL are represented as 'true' or 'false'
                formatted_values.append(value)
            elif isinstance(value, str):
                # Strings will be passed as parameters to avoid SQL injection
                formatted_values.append(value)
            else:
                # Unsupported types are treated as NULL
                formatted_values.append(None)
          # Construct the SQL query with the appropriate number of placeholders
        placeholders = ', '.join(['%s' for _ in formatted_values])
    
        sql_query = f"SELECT * FROM {ptable_name}({placeholders});"

    db_params = charger_parametres_db(papp_name)
    conn = ouvrir_connexion(db_params)

    try:
        cursor = conn.cursor()
        if pmode_sql in ["insert", "update"]:
            cursor.execute(sql_query, values)
            result = cursor.fetchone()
            conn.commit()
            return {"new_id": result[0]} if result else None
        elif pmode_sql == "delete":
            cursor.execute(sql_query)
            deleted_id = cursor.fetchone()[0] if cursor.rowcount > 0 else None
            conn.commit()
            return {"deleted_id": deleted_id} if deleted_id else {"deleted_id": "0"}
        elif pmode_sql == "select":
            cursor.execute(sql_query, tuple(formatted_values))
            conn.commit()
            return cursor.fetchall(), cursor.description
    except Exception as e:
        conn.rollback()
        raise Exception(f"Error in operation: {e}")
    finally:
        cursor.close()
        conn.close()


def create_entry_post_00(json_obj, papp_name, ptable_name,id_name,pmode_sql,pcondition):
    # Extract table name from json object

    # Extract fields and values from json object
    fields = list(json_obj.keys())
    values = list(json_obj.values())
    
    # Build SQL query and set the field name to return as a parameter named pid
    if pmode_sql == "insert":
        sql_query = f"INSERT INTO {ptable_name} ({', '.join(fields)}) VALUES ({', '.join(['%s']*len(fields))}) RETURNING \"{id_name}\" as id;"
    elif pmode_sql == "update":
       # Create a list of 'field = %s' strings, one for each field
        update_assignments = [f"{field} = %s" for field in fields]
            # Join the 'field = %s' strings with commas to form the SET clause
        sql_query = f"UPDATE {ptable_name} SET {', '.join(update_assignments)} WHERE {pcondition} RETURNING \"{id_name}\" as id;"

    elif pmode_sql == "select":
    # List to hold formatted values
        formatted_values = []

        # Iterate over the values and format them according to their type
        for value in values:
            if isinstance(value, int):
                # Integers can be used directly in SQL
                formatted_values.append(value)
            elif isinstance(value, float):
                # Numeric (floating-point) values can also be used directly
                formatted_values.append(value)
            elif isinstance(value, bool):
                # Booleans in PostgreSQL are represented as 'true' or 'false'
                formatted_values.append(value)
            elif isinstance(value, str):
                # Strings will be passed as parameters to avoid SQL injection
                formatted_values.append(value)
            else:
                # Unsupported types are treated as NULL
                formatted_values.append(None)

        # Create a string of '%s' placeholders, one for each formatted value
        placeholders = ', '.join(['%s' for _ in formatted_values])

    # Construct the SQL query with the appropriate number of placeholders
    sql_query = f"SELECT * FROM {ptable_name}({placeholders});"
    
    db_params = charger_parametres_db(papp_name)
    conn = ouvrir_connexion(db_params)
       
    try:
        # Create a cursor
        cursor = conn.cursor()
                # Execute the SQL query
        
        if pmode_sql != "select":
            cursor.execute(sql_query, values)
            # Get the inserted record id
            inserted_id = cursor.fetchone()[0]
            # Commit the transaction
            conn.commit()
            return  {"new_id": inserted_id}
        else:
            cursor.execute(sql_query, tuple(formatted_values))
            conn.commit()
            return cursor.fetchall(), cursor.description
    
    except psycopg2.Error as e:
        # Rollback the transaction in case of error
        conn.rollback()
        raise Exception(f"Error inserting record: {e}")
    finally:
        # Close the cursor and connection
        cursor.close()
        conn.close()
