from flask import Flask, jsonify, request
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)

uri = os.getenv('URI')
user = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
driver = GraphDatabase.driver(uri, auth=(user, password),database="neo4j")

def get_employees(tx, sort=None, filter=None, filterKey=None):
    query = "MATCH (e:Employee) RETURN e"
    print(sort)
    if filter != None and filterKey!=None:
        if filter=='name':
            query = f"MATCH (e:Employee) WHERE e.name CONTAINS '{filterKey}' RETURN e"
        elif filter=='surname':
            query = f"MATCH (e:Employee) WHERE e.surname CONTAINS '{filterKey}' RETURN e"
        elif filter=='position':
            query = f"MATCH (e:Employee) WHERE e.position CONTAINS '{filterKey}' RETURN e" 
    if sort != None:
        if sort == 'name':
            query = f"MATCH (e:Employee) RETURN e ORDER BY e.name"
        elif sort == 'surname':
            query = f"MATCH (e:Employee) RETURN e ORDER BY e.surname"
        elif sort == 'position':
            query = f"MATCH (e:Employee) RETURN e ORDER BY e.position"
    results = tx.run(query).data()
    employees = [{'name': result['e']['name'], 'surname': result['e']['surname'], 'position': result['e']['position']} for result in results]
    return employees

@app.route('/employees', methods=['GET'])
def get_employees_route():
    sort=request.args.get('sort', '')
    filter=request.args.get('filter', '')
    filterKey=request.args.get('filterKey', '')
    with driver.session() as session:
        employees = session.read_transaction(get_employees, sort, filter, filterKey)

    response = {'employees': employees}
    return jsonify(response)


def add_employee(tx, name, surname, position, department):
    query = f"MATCH (m: Employee) WHERE m.name='{name}' AND m.surname='{surname}' RETURN m"
    res=tx.run(query).data()
    if res:
        return False
    else:
        queryEmployee = f"CREATE ({name}:Employee {{name:'{name}', surname:'{surname}', position:'{position}'}})"
        queryRelation = f"MATCH (a:Employee) WHERE a.name = '{name}' AND a.surname = '{surname}' MATCH (b:Department {{name: '{department}'}}) CREATE (a)-[r:WORKS_IN]->(b) RETURN type(r)"
        tx.run(queryEmployee, name=name, surname=surname, position=position)
        tx.run(queryRelation, name=name, surname=surname, department=department)
        return True


@app.route('/employees', methods=['POST'])
def add_employee_route():
    name = request.json['name']
    surname = request.json['surname']
    position = request.json['position']
    department = request.json['department']

    if (name == '' or surname == '' or position == '' or department == ''):
        return jsonify("Missing data in request"), 405

    with driver.session() as session:
        response=session.write_transaction(add_employee, name, surname, position, department)

    if (response == False):
        return jsonify("Employee already exists!"), 400

    return jsonify("User has been added!"), 200


def update_employee(tx, id, name=None, surname=None, position=None, department=None):
    query = f"MATCH (e:Employee) WHERE e.id = '{id}' RETURN e"
    result = tx.run(query).data()

    if len(result)==0:
        return False
    else:
        if name:
            query = f"MATCH (n:Employee) WHERE id(n) = '{id}' SET n.name = $name"
            tx.run(query, internal_id=id, name=name)
        if surname:
            query = f"MATCH (n:Employee) WHERE id(n) = '{id}' SET n.surname = $surname"
            tx.run(query, internal_id=id, surname=surname)
        if position:
            query = f"MATCH (n:Employee) WHERE id(n) = '{id}' SET n.position = $position"
            tx.run(query, internal_id=id, position=position)
        if department:
            query = "MATCH (n:Employee) WHERE id(n) = $id MATCH (n)-[r:WORKS_IN]->(d:Department) MATCH (d2:Department {name: $department}) DELETE r MERGE (n)-[:WORKS_IN]->(d2)"
            tx.run(query, internal_id=id, department=department)
        return True


@app.route('/employee/<int:id>', methods=['PUT'])
def update_employee_route(id):
    data = request.get_json()
    name = data['name']
    surname = data['surname']
    position = data['position']
    department = data['department']

    with driver.session() as session:
        res = session.write_transaction(update_employee, id, name, surname, position, department)

    if not res:
        response = {'message': 'Employee not found'}
        return jsonify(response), 404
    else:
        response = {'status': 'success'}
        return jsonify(response)


def delete_employee(tx, id):
    query = f"MATCH (m:Employee)-[r]-(d:Department) WHERE ID(m) = {id} RETURN m, d, r"
    result = tx.run(query).data()

    if not result:
        return False
    else:
        query = f"MATCH (m: Employee) WHERE ID(m) = {id} DETACH DELETE m"
        tx.run(query)
        return True

@app.route('/employee/<int:id>', methods=['DELETE'])
def delete_employee_route(id):
    with driver.session() as session:
        result = session.write_transaction(delete_employee, id)

    if not result:
        response = {'message': 'Employee not found'}
        return jsonify(response), 404
    else:
        response = {'status': 'success'}
        return jsonify(response)

def get_employee_suboordinates(tx, id):
    query = f"""MATCH (p:Employee), (p1:Employee) 
                WHERE ID(p1) = {id} MATCH (p1)-[r]-(d) 
               WHERE NOT (p)-[:MANAGES]-(:Department) 
               AND (p)-[:WORKS_IN]-(:Department {{name:d.name}}) 
               RETURN p"""
    results = tx.run(query).data()
    workers = [{'name': result['p']['name'],
               'surname': result['p']['surname']} for result in results]
    return workers


@app.route("/employees/<int:id>/subordinates", methods=["GET"])
def get_employee_suboordinates_route(id):
    with driver.session() as session:
        employees = session.read_transaction(get_employee_suboordinates, id)

    response = {'employees': employees}
    return jsonify(response), 200


def get_department_info(tx, id):
    query = f"""MATCH (e:Employee)-[r]->(d:Department)<-[:MANAGES]-(m:Employee)
                WHERE ID(e)={id}
                WITH d, m
                MATCH (es:Employee) -[r]-> (d)
                RETURN d, m, count(es) AS countes;
                """
    result = tx.run(query).data()[0]
    department = {'name': result['d']['name'],
                  'manager': result['m']['name'], 'employees': result['countes']}
    return department


@app.route('/employees/<int:id>/department', methods=['GET'])
def get_department_info_route(id):
    with driver.session() as session:
        department_info = session.execute_read(get_department_info, id)

    response = {'department_info': department_info}
    return jsonify(response), 200



def get_departments(tx, name=None, sort=None):
    query = "MATCH (e:Employee)-[r]->(d:Department)"
    conditions = []
    if name is not None:
        conditions.append("toLower(d.name) CONTAINS toLower($name)")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " RETURN d.name as name, count(r) as number_of_employees,  ID(d) as id"
    if sort == "name_asc":
        query += " ORDER BY d.name"
    elif sort == "name_desc":
        query += " ORDER BY d.name DESC"
    elif sort == "e_asc":
        query += " ORDER BY number_of_employees"
    elif sort == "e_desc":
        query += " ORDER BY number_of_employees DESC"
    results = tx.run(query, name=name).data()
    departments = [{"name": result['name'], "number_of_employees": result['number_of_employees'], "id": result['id']} for result in results]
    return departments


@app.route('/departments', methods=['GET'])
def get_departments_route():
    name = request.args.get('name')
    sort = request.args.get('sort')
    with driver.session() as session:
        departments = session.execute_read(get_departments, name, sort)
    response = {'departments': departments}
    return jsonify(response), 200



def get_department_employees(tx, id):
    query = f"""MATCH (d:Department) 
                WHERE id(d) = {id} 
                RETURN d"""
    result = tx.run(query).data()

    if not result:
        return None

    else:
        query = f"""MATCH (d: Department)<-[r:WORKS_IN]-(e: Employee) 
                    WHERE id(d) = {id}
                    RETURN e"""
        results = tx.run(query).data()
        employees = [{'name': result['e']['name'], 'surname':result['e']['surname'],
                      'position': result['e']['position']} for result in results]
        return employees


@app.route('/departments/<int:id>/employees', methods=['GET'])
def get_department_employees_route(id):
    with driver.session() as session:
        employees = session.execute_read(get_department_employees, id)

    if not employees:
        return jsonify("Department not found"), 404
    else:
        response = {'employees of department': employees}
        return jsonify(response), 200



if __name__ == '__main__':
    app.run()

