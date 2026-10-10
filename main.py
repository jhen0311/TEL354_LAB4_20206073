import yaml
import json
import requests
import asyncio
import aiohttp
import uuid
import re

 
CONTROLLER_IP = "172.16.0.1"     
FLOW_PUSHER_URL = "http://" + CONTROLLER_IP + ":8080/wm/staticflowpusher/json"
 
connections = {}    #

class Student:
    
    def __init__(self, name, mac):
            self.name = name.strip()
            self.mac = mac.lower()  

class Service:
    def __init__(self, name, protocol, port):
        self.name = name
        self.protocol = protocol.upper()
        self.port = int(port)

class Server:
    def __init__(self, name, ip, services):
        self.name = name
        self.ip = ip
        self.services = [Service(s["name"], s["protocol"], s["port"]) for s in services]

    def get_service(self, service_name):
        for s in self.services:
            if s.name == service_name:
                return s
        return None

class Course:
    def __init__(self, name, state, students, servers):
        self.name = name
        self.code = None           
        self.state = state.upper()
        self.students = [s.strip() for s in students]  
        self.servers = servers
 
    def add_student(self, student_name):
        if student_name in self.students:
            return False
        self.students.append(student_name)
        return True
 
    def remove_student(self, student_name):
        if student_name not in self.students:
            return False
        self.students.remove(student_name)
        return True
 
    def add_server(self, server_name, allowed_services):
        self.servers.append({"name": server_name,
                             "allowed_services": list(allowed_services)})
 
    def is_active(self):
        return self.state == "ACTIVE"
 
    def has_access(self, server_name, service_name):
        for s in self.servers:
            if s["name"] == server_name and service_name in s["allowed_services"]:
                return True
        return False


def load_data(filename):
    with open(filename, "r") as file:
        data = yaml.safe_load(file)
    students = [ Student(x["name"], x["mac"]) for x in data["students"] ]
    servers = [ Server(y["name"], y["ip"], y["services"]) for y in data["servers"] ]
    courses = [ Course(z["name"], z["state"], z["students"], z["servers"]) for z in data["courses"] ]
    return students, servers, courses


def get_attachment_point(controller_ip, mac):
    endpoint = '/wm/device/'
    url = 'http://' + controller_ip + ':8080' + endpoint
    response = requests.get(
        url,
        params={'mac': mac}
    )
    result, = response.json()
    attachment_points = result.get("attachmentPoint", [])

    if not attachment_points:
        return None, None

    attachment_point, = attachment_points
    return attachment_point["switchDPID"], attachment_point["port"]


def get_route(controller_ip, src_mac, dst_mac):
    src_sw_dpid, src_sw_port = get_attachment_point(controller_ip, src_mac)
    dst_sw_dpid, dst_sw_port = get_attachment_point(controller_ip, dst_mac)
    endpoint = f'/wm/topology/route/{src_sw_dpid}/{src_sw_port}/{dst_sw_dpid}/{dst_sw_port}/json'
    url = 'http://' + controller_ip + ':8080' + endpoint
    response = requests.get(url)
    return response.json()

# Funciones auxiliares 
 
def find_student(students, name):
    for st in students:
        if st.name.lower() == name.strip().lower():
            return st
    return None
 
 
def find_server(servers, name):
    for sv in servers:
        if sv.name.lower() == name.strip().lower():
            return sv
    return None
 
 
def find_course(courses, key):
    """Busca un curso por codigo (HGW101) o por nombre."""
    key = key.strip().lower()
    for c in courses:
        if (c.code or "").lower() == key or c.name.lower() == key:
            return c
    return None
 
 
def is_authorized(student, server, service_name, courses):
    """Autorizado si esta matriculado en algun curso ACTIVE que tenga al servidor
    y que permita el servicio para ese servidor."""
    for c in courses:
        if c.is_active() and student.name in c.students and c.has_access(server.name, service_name):
            return True
    return False
 
 
def get_device(params):
    """Consulta /wm/device/ con un filtro (mac o ipv4) y devuelve el primer host o None."""
    url = 'http://' + CONTROLLER_IP + ':8080/wm/device/'
    devices = requests.get(url, params=params).json()
    return devices[0] if devices else None
 
 
def port_number(port):
    """La ruta puede devolver el puerto como numero, texto o diccionario."""
    if isinstance(port, dict):
        return port.get("portNumber", port.get("shortPortNumber"))
    return int(port)
 
 
async def send_flow(session, method, flow):
    try:
        async with session.request(method, FLOW_PUSHER_URL, json=flow,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return flow["name"], resp.status, await resp.text()
    except Exception as e:
        return flow["name"], None, str(e)
 
 
async def send_flows(method, flows):
    """Envia todas las peticiones al Static Flow Pusher de forma concurrente."""
    async with aiohttp.ClientSession() as session:
        tasks = [send_flow(session, method, f) for f in flows]
        return await asyncio.gather(*tasks)
 
#Menu
 
def menu():
    print("\n========== MENU PRINCIPAL ==========")
    print("1) Importar")
    print("2) Exportar")
    print("3) Cursos")
    print("4) Alumnos")
    print("5) Servidores")
    print("6) Politicas")
    print("7) Conexiones")
    print("8) Salir")
    return input(">>> Seleccione una opcion: ").strip()
 
 
def submenu(title, options):
    print(f"\n----- {title} -----")
    for i, op in enumerate(options, 1):
        print(f"{i}) {op}")
    print("0) Volver")
    return input(">>> Opcion: ").strip()
 
 
#  Cursos 
 
def menu_courses(students, servers, courses):
    while True:
        op = submenu("CURSOS", ["Listar", "Mostrar detalles", "Gestionar alumnos"])
        if op == "0":
            return
        elif op == "1":
            print("Filtro por acceso (Enter para todos):")
            srv = input("  Servidor: ").strip()
            svc = input("  Servicio: ").strip() if srv else ""
            print(f"\n{'CODIGO':<8} {'NOMBRE':<32} ESTADO")
            for c in courses:
                if srv and not c.has_access(srv, svc):
                    continue
                print(f"{c.code:<8} {c.name:<32} {c.state}")
        elif op == "2":
            c = find_course(courses, input("Codigo del curso: "))
            if not c:
                print("Error: curso no encontrado.")
                continue
            print(f"\nCodigo: {c.code}\nNombre: {c.name}\nEstado: {c.state}")
            print("Alumnos:")
            for name in c.students:
                print(f"  - {name}")
            print("Servidores:")
            for s in c.servers:
                print(f"  - {s['name']}: servicios permitidos {s['allowed_services']}")
        elif op == "3":
            c = find_course(courses, input("Codigo del curso: "))
            if not c:
                print("Error: curso no encontrado.")
                continue
            accion = input("1) Agregar alumno  2) Eliminar alumno: ").strip()
            st = find_student(students, input("Nombre del alumno: "))
            if not st:
                print("Error: el alumno no existe.")
            elif accion == "1":
                print("Alumno agregado." if c.add_student(st.name) else "El alumno ya estaba en el curso.")
            elif accion == "2":
                print("Alumno eliminado." if c.remove_student(st.name) else "El alumno no estaba en el curso.")
 
 
#  Alumnos 
 
def menu_students(students, courses):
    while True:
        op = submenu("ALUMNOS", ["Crear", "Listar", "Mostrar detalles"])
        if op == "0":
            return
        elif op == "1":
            name = input("Nombre: ").strip()
            mac = input("MAC: ").strip()
            if not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac):
                print("Error: MAC invalida.")
            elif find_student(students, name):
                print("Error: ya existe un alumno con ese nombre.")
            else:
                students.append(Student(name, mac))
                print("Alumno creado.")
        elif op == "2":
            course_key = input("Filtrar por codigo de curso (Enter para todos): ").strip()
            course = find_course(courses, course_key) if course_key else None
            if course_key and not course:
                print("Error: curso no encontrado.")
                continue
            print(f"\n{'NOMBRE':<25} MAC")
            for st in students:
                if course and st.name not in course.students:
                    continue
                print(f"{st.name:<25} {st.mac}")
        elif op == "3":
            st = find_student(students, input("Nombre del alumno: "))
            if not st:
                print("Error: alumno no encontrado.")
                continue
            print(f"\nNombre: {st.name}\nMAC: {st.mac}")
 
 
# Servidores 
 
def menu_servers(servers):
    while True:
        op = submenu("SERVIDORES", ["Listar", "Mostrar servicios"])
        if op == "0":
            return
        elif op == "1":
            print(f"\n{'NOMBRE':<12} IP")
            for sv in servers:
                print(f"{sv.name:<12} {sv.ip}")
        elif op == "2":
            sv = find_server(servers, input("Nombre del servidor: "))
            if not sv:
                print("Error: servidor no encontrado.")
                continue
            print(f"\n{sv.name} ({sv.ip})")
            for s in sv.services:
                print(f"  - {s.name}: {s.protocol}/{s.port}")
 
 
# Conexiones
 
def create_connection(students, servers, courses):
    st = find_student(students, input("Nombre del alumno: "))
    sv = find_server(servers, input("Nombre del servidor: "))
    if not st or not sv:
        print("Error: alumno o servidor no encontrado.")
        return
    svc = sv.get_service(input(f"Servicio {[s.name for s in sv.services]}: ").strip())
    if not svc:
        print("Error: el servidor no ofrece ese servicio.")
        return
 
    if not is_authorized(st, sv, svc.name, courses):
        print(f"Error: {st.name} NO esta autorizado a acceder a {svc.name} en {sv.name}.")
        return
 
    try:
        server_dev = get_device({"ipv4": sv.ip})
        if not server_dev:
            print("Error: el controlador aun no conoce al servidor (genere trafico desde el).")
            return
        server_mac = server_dev["mac"][0]
        student_dev = get_device({"mac": st.mac})
        student_ip = student_dev["ipv4"][0] if student_dev and student_dev["ipv4"] else None
 
        if None in get_attachment_point(CONTROLLER_IP, st.mac) or \
           None in get_attachment_point(CONTROLLER_IP, server_mac):
            print("Error: no se conoce el punto de conexion del alumno o del servidor.")
            return
        route = get_route(CONTROLLER_IP, st.mac, server_mac)
    except Exception as e:
        print("Error consultando al controlador:", e)
        return
 
    if not route:
        print("Error: el controlador no encontro una ruta.")
        return
 
    handler = uuid.uuid4().hex[:8]
    flow_names = build_route(route, st.mac, student_ip, sv.ip, server_mac, svc, handler)
    if flow_names:
        connections[handler] = {"student": st, "server": sv, "service": svc,
                                "flows": flow_names, "route": route}
        print(f"Conexion creada. Handler: {handler}")
 
 
def delete_connection(courses):
    handler = input("Handler de la conexion: ").strip()
    conn = connections.get(handler)
    if not conn:
        print("Error: no existe una conexion con ese handler.")
        return
    if not is_authorized(conn["student"], conn["server"], conn["service"].name, courses):
        print(f"Error: {conn['student'].name} no esta autorizado a ese servicio.")
        return
    results = asyncio.run(send_flows("DELETE", [{"name": n} for n in conn["flows"]]))
    for name, status, text in results:
        print(f"  {name}: {status} {text.strip()}")
    del connections[handler]
    print("Conexion eliminada.")
 
 
def menu_connections(students, servers, courses):
    while True:
        op = submenu("CONEXIONES", ["Crear", "Listar", "Borrar"])
        if op == "0":
            return
        elif op == "1":
            create_connection(students, servers, courses)
        elif op == "2":
            if not connections:
                print("No hay conexiones creadas.")
            for h, c in connections.items():
                print(f"{h}: {c['student'].name} -> {c['server'].name} "
                      f"({c['service'].name} {c['service'].protocol}/{c['service'].port}) "
                      f"[{len(c['flows'])} flows]")
        elif op == "3":
            delete_connection(courses)
 

# build_route

def build_route(route, student_mac, student_ip, server_ip, server_mac, service, handler):
    """Recibe la ruta (lista de pares switch/puerto entre las dos MAC) y los datos de la
    conexion. Por cada switch instala flows en ambos sentidos con match L2/L3/L4 solo
    para el servicio pedido, mas los flows de ARP. La insercion es asincrona."""
    if service.protocol == "TCP":
        ip_proto, l4 = "0x06", "tcp"
    else:
        ip_proto, l4 = "0x11", "udp"
 
    flows = []
    for i in range(0, len(route) - 1, 2):
        dpid = route[i]["switch"]
        in_port = port_number(route[i]["port"])          # puerto hacia el alumno
        out_port = port_number(route[i + 1]["port"])     # puerto hacia el servidor
        base = f"{handler}_sw{i // 2}"
        common = {"switch": dpid, "priority": "40000", "active": "true"}
 
        # alumno -> servidor (L2 + L3 + L4)
        fwd = dict(common, name=f"{base}_fwd", in_port=str(in_port),
                   eth_type="0x0800", eth_src=student_mac, eth_dst=server_mac,
                   ipv4_dst=server_ip, ip_proto=ip_proto,
                   actions=f"output={out_port}")
        fwd[f"{l4}_dst"] = str(service.port)
        # servidor -> alumno (L2 + L3 + L4)
        rev = dict(common, name=f"{base}_rev", in_port=str(out_port),
                   eth_type="0x0800", eth_src=server_mac, eth_dst=student_mac,
                   ipv4_src=server_ip, ip_proto=ip_proto,
                   actions=f"output={in_port}")
        rev[f"{l4}_src"] = str(service.port)
        if student_ip:
            fwd["ipv4_src"] = student_ip
            rev["ipv4_dst"] = student_ip
 
        # ARP en ambos sentidos
        arp_fwd = dict(common, name=f"{base}_arp_fwd", in_port=str(in_port),
                       eth_type="0x0806", eth_src=student_mac, actions=f"output={out_port}")
        arp_rev = dict(common, name=f"{base}_arp_rev", in_port=str(out_port),
                       eth_type="0x0806", eth_src=server_mac, actions=f"output={in_port}")
 
        flows += [fwd, rev, arp_fwd, arp_rev]
 
    results = asyncio.run(send_flows("POST", flows))
    ok = True
    for name, status, text in results:
        print(f"  {name}: {status} {text.strip()}")
        if status != 200:
            ok = False
    if not ok:
        print("Algunos flows fallaron.")
    return [f["name"] for f in flows]

#main
def main():
    # Load data
    students, servers, courses = load_data("database.yaml")
    # print(get_attachment_point('10.100.18.253','a2:9a:f5:03:a0:65'))
    # print(json.dumps(get_route('10.100.18.253', "e6:3e:13:dc:ed:37","a6:96:21:fb:ca:a7"), indent=4))

    # ADD YOUR CODE HERE
    with open("database.yaml", "r") as file:
        raw = yaml.safe_load(file)
    for course, data in zip(courses, raw["courses"]):
        course.code = data.get("code")
 
    while True:
        op = menu()
        if op == "3":
            menu_courses(students, servers, courses)
        elif op == "4":
            menu_students(students, courses)
        elif op == "5":
            menu_servers(servers)
        elif op == "7":
            menu_connections(students, servers, courses)
        elif op == "8":
            print("Saliendo...")
            break
        elif op in ("1", "2", "6"):
            print("Opcion no requerida en este laboratorio.")
        else:
            print("Opcion invalida.")

if __name__ == "__main__":
    main()

