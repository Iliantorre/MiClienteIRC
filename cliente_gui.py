"""Mi Cliente IRC — interfaz gráfica (Tkinter)."""
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import messagebox, simpledialog, ttk

import config
from config import COMANDOS_INTERNOS, TEMAS, VERSION
from dialogos import Preferencias
from irc_core import IRCConexion, parsear

try:  # texto nítido en pantallas con escala alta (Windows)
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

PREFIJOS = "~&@%+!"
RANGO = {"~": 0, "&": 0, "!": 0, "@": 1, "%": 2, "+": 3}
ENLACE = re.compile(r"https?://[^\s<>\"']+")
NUM_WHOIS = {"301", "307", "311", "312", "313", "317", "318", "319", "330",
             "335", "338", "378", "379", "671"}
NECESITAN_RED = ("join", "part", "msg", "nick", "me", "raw", "topic", "whois",
                 "notice", "away", "kick", "mode")


# ---------- Funciones puras (fáciles de probar) ----------
def expandir_alias(plantilla, arg, nick, canal):
    """Convierte un alias en la lista de comandos que debe ejecutar."""
    params = arg.split()

    def reemplazo(m):
        n = int(m.group(1))
        if m.group(2):
            return " ".join(params[n - 1:])
        return params[n - 1] if n <= len(params) else ""

    salida = []
    for trozo in plantilla.split("|"):
        trozo = trozo.strip()
        if not trozo:
            continue
        trozo = trozo.replace("$me", nick).replace("$chan", canal)
        trozo = re.sub(r"\$([1-9])(-?)", reemplazo, trozo)
        salida.append(trozo.strip())
    return salida


def version_tupla(v):
    partes = []
    for x in str(v).split("."):
        m = re.match(r"\d+", x.strip())
        partes.append(int(m.group()) if m else 0)
    return tuple((partes + [0] * 4)[:4])


# ---------- Barra de envío estilo iOS ----------
class BarraEnvio(tk.Canvas):
    """Campo de texto en forma de píldora con botón circular de enviar."""
    ALTO = 56

    def __init__(self, padre, al_enviar):
        super().__init__(padre, height=self.ALTO, highlightthickness=0, bd=0)
        self.al_enviar = al_enviar
        self.t = None
        self.entrada = tk.Entry(self, relief="flat", bd=0, highlightthickness=0)
        self._item_entrada = self.create_window(0, 0, window=self.entrada, anchor="w")
        self.bind("<Configure>", lambda e: self._dibujar())
        self.tag_bind("enviar", "<Button-1>", lambda e: self.al_enviar())
        self.tag_bind("enviar", "<Enter>", lambda e: self.config(cursor="hand2"))
        self.tag_bind("enviar", "<Leave>", lambda e: self.config(cursor=""))

    def aplicar_estilo(self, t, fuente):
        self.t = t
        self.configure(bg=t["bg"])
        self.entrada.configure(bg=t["campo"], fg=t["campo_fg"],
                               insertbackground=t["campo_fg"], font=fuente)
        self._dibujar()

    def _redondo(self, x1, y1, x2, y2, r, **kw):
        p = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
             x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(p, smooth=True, **kw)

    def _dibujar(self):
        if self.t is None:
            return
        self.delete("dibujo")
        w = self.winfo_width()
        if w < 80:
            return
        y1, y2 = 9, self.ALTO - 9
        x1, x2 = 10, w - 10
        self._redondo(x1, y1, x2, y2, (y2 - y1) // 2, fill=self.t["campo"],
                      outline=self.t["separador"], width=1, tags="dibujo")
        d = y2 - y1 - 8
        cy = (y1 + y2) // 2
        cx = x2 - 4 - d // 2
        self.create_oval(cx - d // 2, cy - d // 2, cx + d // 2, cy + d // 2,
                         fill=self.t["acento"], outline=self.t["acento"],
                         tags=("dibujo", "enviar"))
        self.create_text(cx, cy - 1, text="↑", fill="#ffffff",
                         font=("Segoe UI", 13, "bold"), tags=("dibujo", "enviar"))
        self.coords(self._item_entrada, x1 + 18, cy)
        self.itemconfigure(self._item_entrada, width=max(40, cx - d // 2 - 10 - (x1 + 18)))


# ---------- Ventana (pestaña o ventana separada) ----------
class Ventana(ttk.Frame):
    """Estado, un canal o un chat privado."""

    def __init__(self, padre, app, nombre, tipo):
        super().__init__(padre)
        self.app = app
        self.nombre = nombre
        self.tipo = tipo              # "estado", "canal" o "privado"
        self.usuarios = {}            # nick -> prefijo (@, +, ...)
        self.top = None               # Toplevel si está en ventana separada
        self.historial = []
        self.pos_hist = 0
        self.ultimo_emisor = None     # para agrupar burbujas seguidas de la misma persona
        self.ultimo_tiempo = 0.0
        self.tema_var = tk.StringVar(value="Mensaje privado" if tipo == "privado" else "")

        if tipo != "estado":          # encabezado centrado, como la barra de Mensajes
            cab = ttk.Frame(self, style="Cab.TFrame")
            cab.pack(side="top", fill="x")
            ttk.Label(cab, text=nombre, anchor="center", style="CabTitulo.TLabel").pack(
                fill="x", pady=(10, 0))
            ttk.Label(cab, textvariable=self.tema_var, anchor="center", style="CabSub.TLabel").pack(
                fill="x", padx=16, pady=(0, 10))
            ttk.Separator(self, orient="horizontal").pack(side="top", fill="x")

        self.barra_envio = BarraEnvio(self, lambda: self.app.al_enviar(self))
        self.barra_envio.pack(side="bottom", fill="x")
        self.entrada = self.barra_envio.entrada
        cuerpo = ttk.Frame(self)
        cuerpo.pack(fill="both", expand=True)

        self.lista = None
        if tipo == "canal":
            panel = ttk.Frame(cuerpo)
            panel.pack(side="right", fill="y", padx=(0, 8))
            self.lbl_usuarios = ttk.Label(panel, text="Usuarios")
            self.lbl_usuarios.pack(anchor="w", pady=(8, 4), padx=4)
            self.lista = tk.Listbox(panel, width=20, exportselection=False)
            self.lista.pack(fill="y", expand=True)
            self.lista.bind("<Double-Button-1>", self._abrir_privado)

        self.texto = tk.Text(cuerpo, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(cuerpo, command=self.texto.yview)
        self.texto.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.texto.pack(side="left", fill="both", expand=True)

        for nombre_tag in ("enlace", "enlace_propio"):
            self.texto.tag_bind(nombre_tag, "<Button-1>",
                                lambda e, n=nombre_tag: self._abrir_enlace(e, n))
            self.texto.tag_bind(nombre_tag, "<Enter>", lambda e: self.texto.config(cursor="hand2"))
            self.texto.tag_bind(nombre_tag, "<Leave>", lambda e: self.texto.config(cursor=""))

        self.entrada.bind("<Return>", lambda e: self.app.al_enviar(self))
        self.entrada.bind("<Up>", self._hist_arriba)
        self.entrada.bind("<Down>", self._hist_abajo)
        self.entrada.bind("<Tab>", self._completar)

    # --- estilo ---
    def aplicar_estilo(self, t, fuente):
        fam, tam = fuente
        peq = (fam, max(8, tam - 2))
        self.texto.configure(bg=t["campo"], fg=t["campo_fg"], font=fuente,
                             insertbackground=t["campo_fg"], selectbackground=t["acento"],
                             selectforeground="#ffffff", relief="flat", highlightthickness=0,
                             padx=4, pady=10)
        if self.lista is not None:
            self.lista.configure(bg=t["bg"], fg=t["fg"], font=fuente,
                                 selectbackground=t["acento"], selectforeground="#ffffff",
                                 relief="flat", highlightthickness=0, activestyle="none")
        self.barra_envio.aplicar_estilo(t, fuente)

        tx = self.texto
        lat = 150   # espacio libre al lado opuesto: limita el ancho de las burbujas
        # Párrafos (alineación y márgenes)
        tx.tag_configure("p_propio", justify="right", lmargin1=lat, lmargin2=lat,
                         rmargin=16, spacing1=1, spacing3=1)
        tx.tag_configure("p_otro", justify="left", lmargin1=16, lmargin2=16,
                         rmargin=lat, spacing1=1, spacing3=1)
        tx.tag_configure("p_meta_propio", justify="right", lmargin1=lat, lmargin2=lat,
                         rmargin=22, spacing1=8)
        tx.tag_configure("p_meta_otro", justify="left", lmargin1=22, lmargin2=22,
                         rmargin=lat, spacing1=8)
        tx.tag_configure("p_centro", justify="center", lmargin1=24, lmargin2=24,
                         rmargin=24, spacing1=4, spacing3=4)
        tx.tag_configure("p_log", lmargin1=8, lmargin2=8, spacing3=2)
        # Colores
        tx.tag_configure("meta", foreground=t["hora"], font=peq)
        tx.tag_configure("hora", foreground=t["hora"], font=peq)
        tx.tag_configure("sistema", foreground=t["sistema"], font=peq)
        tx.tag_configure("aviso", foreground=t["aviso"], font=peq)
        tx.tag_configure("accion", foreground=t["accion"], font=peq)
        tx.tag_configure("b_propio", background=t["burbuja_propia"], foreground=t["burbuja_propia_fg"])
        tx.tag_configure("b_otro", background=t["burbuja_otro"], foreground=t["burbuja_otro_fg"])
        tx.tag_configure("b_mencion", background=t["mencion"], foreground=t["mencion_fg"])
        tx.tag_configure("enlace", foreground=t["enlace"], underline=True)
        tx.tag_configure("enlace_propio", foreground=t["burbuja_propia_fg"], underline=True)

    # --- texto ---
    def _abrir_enlace(self, evento, nombre_tag):
        indice = self.texto.index(f"@{evento.x},{evento.y}")
        rango = self.texto.tag_prevrange(nombre_tag, f"{indice}+1c")
        if rango:
            webbrowser.open(self.texto.get(*rango))

    def _poner(self, texto, tags):
        if not texto:
            return
        if tags:
            self.texto.insert("end", texto, tags)
        else:
            self.texto.insert("end", texto)

    def _insertar(self, texto, base=()):
        enlace = "enlace_propio" if "b_propio" in base else "enlace"
        pos = 0
        for m in ENLACE.finditer(texto):
            self._poner(texto[pos:m.start()], base)
            self._poner(m.group(), base + (enlace,))
            pos = m.end()
        self._poner(texto[pos:], base)

    def _comenzar(self):
        en_fondo = self.texto.yview()[1] >= 0.999
        self.texto.configure(state="normal")
        return en_fondo

    def _terminar(self, en_fondo):
        if int(self.texto.index("end-1c").split(".")[0]) > 5000:
            self.texto.delete("1.0", "501.0")
        self.texto.configure(state="disabled")
        if en_fondo:
            self.texto.see("end")
        self.app.marcar_actividad(self)

    def escribir(self, mensaje, etiqueta=""):
        """Avisos y eventos: centrados y pequeños en canales; como registro en Estado."""
        en_fondo = self._comenzar()
        if self.tipo == "estado":
            hora = self.app.marca_hora()
            if hora:
                self._poner(hora, ("p_log", "hora"))
            self._insertar(mensaje, ("p_log", etiqueta) if etiqueta else ("p_log",))
            self._poner("\n", ("p_log",))
        else:
            self.ultimo_emisor = None     # un aviso corta el agrupado de burbujas
            self._insertar(mensaje, ("p_centro", etiqueta) if etiqueta else ("p_centro",))
            self._poner("\n", ("p_centro",))
        self._terminar(en_fondo)

    def escribir_chat(self, nick, mensaje, propio=False, resaltar=False):
        """Mensaje de chat: burbuja azul a la derecha (tuyo) o gris a la izquierda."""
        en_fondo = self._comenzar()
        if self.tipo == "estado":
            self._insertar(f"<{nick}> {mensaje}", ("p_log",))
            self._poner("\n", ("p_log",))
            self._terminar(en_fondo)
            return
        ahora = time.time()
        nuevo = nick != self.ultimo_emisor or ahora - self.ultimo_tiempo > 300
        self.ultimo_emisor, self.ultimo_tiempo = nick, ahora
        hora = self.app.hora_texto()
        if nuevo:
            if propio:
                if hora:
                    self._poner(hora + "\n", ("p_meta_propio", "meta"))
            else:
                self._poner(nick + (f"   {hora}" if hora else "") + "\n", ("p_meta_otro", "meta"))
        p = "p_propio" if propio else "p_otro"
        b = "b_propio" if propio else ("b_mencion" if resaltar else "b_otro")
        self._poner("\u00a0\u00a0", (p, b))
        self._insertar(mensaje, (p, b))
        self._poner("\u00a0\u00a0", (p, b))
        self._poner("\n", (p,))
        self._terminar(en_fondo)

    def limpiar(self):
        self.ultimo_emisor = None
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        self.texto.configure(state="disabled")

    # --- usuarios ---
    def refrescar_usuarios(self):
        if self.lista is None:
            return
        self.lista.delete(0, "end")
        orden = sorted(self.usuarios.items(),
                       key=lambda it: (RANGO.get(it[1], 4), it[0].lower()))
        for nick, pref in orden:
            self.lista.insert("end", pref + nick)
        self.lbl_usuarios.configure(text=f"Usuarios ({len(self.usuarios)})")

    def _abrir_privado(self, evento=None):
        sel = self.lista.curselection()
        if sel:
            nick = self.lista.get(sel[0]).lstrip(PREFIJOS)
            if nick and nick.lower() != self.app.nick.lower():
                self.app.obtener_ventana(nick, "privado", seleccionar=True)

    # --- entrada: historial y autocompletar ---
    def _hist_arriba(self, evento):
        if self.historial and self.pos_hist > 0:
            self.pos_hist -= 1
            self.entrada.delete(0, "end")
            self.entrada.insert(0, self.historial[self.pos_hist])
        return "break"

    def _hist_abajo(self, evento):
        self.entrada.delete(0, "end")
        if self.pos_hist < len(self.historial) - 1:
            self.pos_hist += 1
            self.entrada.insert(0, self.historial[self.pos_hist])
        else:
            self.pos_hist = len(self.historial)
        return "break"

    def _completar(self, evento):
        texto = self.entrada.get()
        inicio = texto.rfind(" ") + 1
        palabra = texto[inicio:]
        if palabra and self.usuarios:
            coincide = sorted(n for n in self.usuarios if n.lower().startswith(palabra.lower()))
            if coincide:
                nuevo = coincide[0] + (": " if inicio == 0 else " ")
                self.entrada.delete(inicio, "end")
                self.entrada.insert(inicio, nuevo)
        return "break"


# ---------- Aplicación ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = config.cargar()
        self.title(f"Mi Cliente IRC {VERSION}")
        try:
            self.geometry(self.cfg["geometria"])
        except tk.TclError:
            self.geometry("1100x680")
        self.minsize(720, 440)

        self.cola = queue.Queue()
        self.irc = IRCConexion(self.cola)
        self.nick = self.cfg["nick"]
        self.registrado = False
        self.ventanas = {}          # nombre en minúsculas -> Ventana
        self.pendientes = {}        # listas de usuarios que llegan en bloques (353)
        self.ultimo_whois = None
        self.servidor = None
        self.estado_var = tk.StringVar(value="○ Desconectado")

        self.barra_estado = ttk.Frame(self, style="Barra.TFrame")
        self.barra_estado.pack(side="bottom", fill="x")
        ttk.Label(self.barra_estado, textvariable=self.estado_var, anchor="w",
                  padding=(14, 8), style="Barra.TLabel").pack(side="left", fill="x", expand=True)
        self.btn_conexion = ttk.Button(self.barra_estado, text="Conectar", command=self.alternar_conexion)
        self.btn_conexion.pack(side="right", padx=10, pady=5)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._al_cambiar_pestana)
        self.notebook.bind("<Button-3>", self._menu_pestana)

        self._crear_menu()
        self.aplicar_tema()
        self.ventana_estado = self.obtener_ventana("Estado", "estado")
        self.ventana_estado.escribir(f"Mi Cliente IRC {VERSION}. Escribe /ayuda para ver los comandos.", "sistema")

        self.bind("<Control-o>", lambda e: self.abrir_preferencias())
        self.bind("<Control-j>", lambda e: self.entrar_a_canal())
        self.protocol("WM_DELETE_WINDOW", self.cerrar_app)
        self.after(100, self.revisar_cola)
        if self.cfg["autoconectar"]:
            self.after(300, self.conectar)
        else:
            self.ventana_estado.escribir("No estás conectado. Pulsa «Conectar» abajo a la derecha "
                                         "cuando quieras entrar al servidor.", "sistema")
        if self.cfg["buscar_al_inicio"] and self.cfg["url_actualizacion"]:
            self.after(2500, lambda: self.buscar_actualizacion(silencioso=True))

    # ---------- Tema ----------
    def tema(self):
        return TEMAS[self.cfg["tema"]]

    def marca_hora(self):
        if not self.cfg["mostrar_hora"]:
            return ""
        try:
            return f"[{time.strftime(self.cfg['formato_hora'])}] "
        except ValueError:
            return f"[{time.strftime('%H:%M')}] "

    def hora_texto(self):
        if not self.cfg["mostrar_hora"]:
            return ""
        try:
            return time.strftime(self.cfg["formato_hora"])
        except ValueError:
            return time.strftime("%H:%M")

    def aplicar_tema(self):
        t = self.tema()
        fam, tam = self.cfg["fuente"], self.cfg["tamano"]
        fuente = (fam, tam)
        peq = (fam, max(8, tam - 2))
        st = ttk.Style(self)
        if "clam" in st.theme_names():
            st.theme_use("clam")
        self.configure(bg=t["bg"])
        st.configure(".", background=t["bg"], foreground=t["fg"], fieldbackground=t["campo"],
                     bordercolor=t["separador"], lightcolor=t["bg"], darkcolor=t["bg"],
                     troughcolor=t["bg"], focuscolor=t["bg"], font=("Segoe UI", 10))
        st.configure("TNotebook", background=t["bg"], borderwidth=0, tabmargins=(10, 8, 10, 0))
        st.configure("TNotebook.Tab", background=t["bg"], foreground=t["hora"],
                     padding=(16, 8), borderwidth=0)
        st.map("TNotebook.Tab",
               background=[("selected", t["campo"]), ("active", t["campo"])],
               foreground=[("selected", t["acento"])])
        st.configure("TEntry", fieldbackground=t["campo"], foreground=t["campo_fg"],
                     insertcolor=t["campo_fg"], padding=6)
        st.configure("TSpinbox", fieldbackground=t["campo"], foreground=t["campo_fg"],
                     arrowcolor=t["fg"], insertcolor=t["campo_fg"])
        st.configure("TCombobox", fieldbackground=t["campo"], background=t["bg"],
                     foreground=t["campo_fg"], arrowcolor=t["fg"],
                     selectbackground=t["campo"], selectforeground=t["campo_fg"])
        st.map("TCombobox", fieldbackground=[("readonly", t["campo"])],
               foreground=[("readonly", t["campo_fg"])])
        st.configure("TButton", background=t["acento"], foreground="#ffffff",
                     padding=(16, 7), borderwidth=0, focusthickness=0)
        st.map("TButton", background=[("pressed", t["acento"]), ("active", t["acento"])])
        st.configure("TCheckbutton", background=t["bg"], foreground=t["fg"])
        st.configure("TRadiobutton", background=t["bg"], foreground=t["fg"])
        st.configure("TSeparator", background=t["separador"])
        st.configure("Vertical.TScrollbar", background=t["separador"], troughcolor=t["campo"],
                     arrowcolor=t["fg"], bordercolor=t["campo"])
        st.configure("Barra.TFrame", background=t["campo"])
        st.configure("Barra.TLabel", background=t["campo"], foreground=t["hora"], font=peq)
        st.configure("Cab.TFrame", background=t["campo"])
        st.configure("CabTitulo.TLabel", background=t["campo"], foreground=t["fg"],
                     font=(fam, tam + 1, "bold"))
        st.configure("CabSub.TLabel", background=t["campo"], foreground=t["hora"], font=peq)
        self.option_add("*TCombobox*Listbox.background", t["campo"])
        self.option_add("*TCombobox*Listbox.foreground", t["campo_fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["acento"])
        for v in list(self.ventanas.values()):
            v.aplicar_estilo(t, fuente)
            if v.top is not None:
                v.top.configure(bg=t["bg"])

    # ---------- Menú ----------
    def _crear_menu(self):
        barra = tk.Menu(self)
        m1 = tk.Menu(barra, tearoff=0)
        m1.add_command(label="Conectar", command=self.conectar)
        self.menu_servidores = tk.Menu(m1, tearoff=0)
        m1.add_cascade(label="Conectar a…", menu=self.menu_servidores)
        m1.add_command(label="Desconectar", command=self.desconectar)
        m1.add_separator()
        m1.add_command(label="Preferencias…   Ctrl+O", command=self.abrir_preferencias)
        m1.add_separator()
        m1.add_command(label="Salir", command=self.cerrar_app)
        barra.add_cascade(label="Conexión", menu=m1)

        m2 = tk.Menu(barra, tearoff=0)
        m2.add_command(label="Entrar a un canal…   Ctrl+J", command=self.entrar_a_canal)
        m2.add_command(label="Chat privado…", command=self.nuevo_privado)
        m2.add_command(label="Cambiar nick…", command=self.cambiar_nick)
        barra.add_cascade(label="Comandos", menu=m2)

        m3 = tk.Menu(barra, tearoff=0)
        m3.add_command(label="Cerrar pestaña actual", command=self.cerrar_pestana_actual)
        barra.add_cascade(label="Ventana", menu=m3)

        m4 = tk.Menu(barra, tearoff=0)
        m4.add_command(label="Lista de comandos", command=lambda: self.comando("ayuda", self.ventana_estado))
        m4.add_command(label="Buscar actualizaciones…", command=self.buscar_actualizacion)
        m4.add_separator()
        m4.add_command(label="Acerca de", command=self.acerca_de)
        barra.add_cascade(label="Ayuda", menu=m4)
        self.config(menu=barra)
        self._reconstruir_menu_servidores()

    def _reconstruir_menu_servidores(self):
        m = self.menu_servidores
        m.delete(0, "end")
        for i, s in enumerate(self.cfg["servidores"]):
            marca = "● " if i == self.cfg["servidor_activo"] else "    "
            m.add_command(label=f"{marca}{s['nombre']}  ({s['host']}:{s['puerto']})",
                          command=lambda i=i: self.conectar_a(i))
        m.add_separator()
        m.add_command(label="Administrar servidores…", command=lambda: self.abrir_preferencias(1))

    def abrir_preferencias(self, pestana=0):
        Preferencias(self, self.cfg, self.al_guardar_config, self.buscar_actualizacion, pestana)

    def al_guardar_config(self):
        self._reconstruir_menu_servidores()
        self.aplicar_tema()
        self.ventana_estado.escribir("Preferencias guardadas.", "sistema")

    def acerca_de(self):
        messagebox.showinfo("Acerca de", f"Mi Cliente IRC\nVersión {VERSION}\n\n"
                            "Cliente IRC hecho con Python y Tkinter.", parent=self)

    # ---------- Ventanas ----------
    def obtener_ventana(self, nombre, tipo, seleccionar=False):
        clave = nombre.lower()
        v = self.ventanas.get(clave)
        if v is None:
            if tipo != "estado" and self.cfg["modo_ventanas"] == "ventanas":
                top = tk.Toplevel(self)
                top.title(nombre)
                n = len(self.ventanas)
                top.geometry(f"780x480+{120 + 28 * n}+{90 + 28 * n}")
                top.configure(bg=self.tema()["bg"])
                v = Ventana(top, self, nombre, tipo)
                v.top = top
                v.pack(fill="both", expand=True)
                top.protocol("WM_DELETE_WINDOW", lambda v=v: self.cerrar_ventana(v))
            else:
                v = Ventana(self.notebook, self, nombre, tipo)
                self.notebook.add(v, text=f" {nombre} ")
            self.ventanas[clave] = v
            v.aplicar_estilo(self.tema(), (self.cfg["fuente"], self.cfg["tamano"]))
        if seleccionar:
            self.mostrar(v)
        return v

    def mostrar(self, v):
        if v.top is not None:
            v.top.deiconify()
            v.top.lift()
        else:
            self.notebook.select(v)
        v.entrada.focus_set()

    def cerrar_ventana(self, v, enviar_part=True):
        if v is None or v.tipo == "estado":
            return
        if v.tipo == "canal" and enviar_part and self.irc.activo:
            self.irc.enviar(f"PART {v.nombre}")
        self.ventanas.pop(v.nombre.lower(), None)
        if v.top is not None:
            v.top.destroy()
        else:
            self.notebook.forget(v)
            v.destroy()

    def cerrar_pestana_actual(self):
        sel = self.notebook.select()
        if sel:
            v = self.nametowidget(sel)
            if isinstance(v, Ventana):
                self.cerrar_ventana(v)

    def marcar_actividad(self, v):
        if v.top is not None or v.tipo == "estado":
            return
        try:
            if self.notebook.select() != str(v):
                self.notebook.tab(v, text=f" {v.nombre} • ")
        except tk.TclError:
            pass

    def _al_cambiar_pestana(self, evento=None):
        sel = self.notebook.select()
        if not sel:
            return
        try:
            v = self.nametowidget(sel)
        except (KeyError, tk.TclError):
            return
        if isinstance(v, Ventana):
            if v.tipo != "estado":
                self.notebook.tab(v, text=f" {v.nombre} ")
            v.entrada.focus_set()

    def _menu_pestana(self, evento):
        try:
            i = self.notebook.index(f"@{evento.x},{evento.y}")
            v = self.nametowidget(self.notebook.tabs()[i])
        except (tk.TclError, KeyError, IndexError):
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cerrar", command=lambda: self.cerrar_ventana(v),
                         state="disabled" if v.tipo == "estado" else "normal")
        menu.add_command(label="Limpiar", command=v.limpiar)
        menu.tk_popup(evento.x_root, evento.y_root)

    # ---------- Conexión ----------
    def alternar_conexion(self):
        if self.irc.ocupado:
            self.desconectar()
        else:
            self.conectar()

    def conectar(self):
        if self.irc.activo:
            return
        lista = self.cfg["servidores"]
        s = lista[min(self.cfg["servidor_activo"], len(lista) - 1)]
        self.servidor = s
        self.registrado = False
        self.nick = self.cfg["nick"]
        ok = self.irc.conectar(s["host"], s["puerto"], s["tls"], s["tls_nombre"],
                               self.cfg["nick"], self.cfg["usuario"], self.cfg["nombre_real"], s["clave"])
        if ok:
            self.ventana_estado.escribir(f"Conectando a {s['nombre']} ({s['host']}:{s['puerto']})...", "sistema")
            self.estado_var.set(f"◌ Conectando a {s['nombre']}…")
            self.btn_conexion.configure(text="Desconectar")
        else:
            self.ventana_estado.escribir("Espera un momento e inténtalo de nuevo.", "aviso")

    def conectar_a(self, i):
        self.cfg["servidor_activo"] = i
        try:
            config.guardar(self.cfg)
        except OSError:
            pass
        self._reconstruir_menu_servidores()
        if self.irc.activo:
            self.irc.desconectar(self.cfg["mensaje_quit"])
        self.esperar_y_conectar()

    def esperar_y_conectar(self, intentos=15):
        if self.irc.ocupado and intentos > 0:
            self.after(300, lambda: self.esperar_y_conectar(intentos - 1))
        else:
            self.conectar()

    def desconectar(self):
        self.irc.desconectar(self.cfg["mensaje_quit"])

    def cerrar_app(self):
        try:
            self.cfg["geometria"] = self.geometry()
            config.guardar(self.cfg)
        except Exception:
            pass
        self.irc.desconectar(self.cfg["mensaje_quit"])
        self.destroy()

    def _estado_conectado(self):
        nombre = self.servidor["nombre"] if self.servidor else ""
        self.estado_var.set(f"● {nombre} — {self.nick}")

    # ---------- Diálogos rápidos ----------
    def entrar_a_canal(self):
        canal = simpledialog.askstring("Entrar a un canal", "Nombre del canal (ej. #amigos):", parent=self)
        if canal and canal.strip():
            self.comando(f"join {canal.strip()}", self.ventana_estado)

    def nuevo_privado(self):
        nick = simpledialog.askstring("Chat privado", "Nick de la persona:", parent=self)
        if nick and nick.strip():
            self.obtener_ventana(nick.strip().split()[0], "privado", seleccionar=True)

    def cambiar_nick(self):
        nick = simpledialog.askstring("Cambiar nick", "Nuevo nick:", initialvalue=self.nick, parent=self)
        if nick and nick.strip():
            self.comando(f"nick {nick.strip()}", self.ventana_estado)

    # ---------- Entrada del usuario ----------
    def al_enviar(self, v):
        texto = v.entrada.get().strip()
        v.entrada.delete(0, "end")
        if not texto:
            return
        v.historial.append(texto)
        v.historial = v.historial[-100:]
        v.pos_hist = len(v.historial)
        self.ejecutar(texto, v)

    def ejecutar(self, linea, v, profundidad=0):
        linea = linea.strip()
        if not linea:
            return
        if linea.startswith("/") and not linea.startswith("//"):
            self.comando(linea[1:], v, profundidad)
        else:
            self.decir(v, linea[1:] if linea.startswith("//") else linea)

    def decir(self, v, texto):
        if v is None or v.tipo == "estado":
            self.ventana_estado.escribir("No estás en un canal. Usa /join #canal", "aviso")
            return
        if not self.irc.activo:
            v.escribir("No estás conectado.", "aviso")
            return
        for i in range(0, len(texto), 350):   # el protocolo limita el largo de cada línea
            trozo = texto[i:i + 350]
            self.irc.enviar(f"PRIVMSG {v.nombre} :{trozo}")
            v.escribir_chat(self.nick, trozo, propio=True)

    def comando(self, linea, v, profundidad=0):
        partes = linea.split(" ", 1)
        cmd = partes[0].lower()
        arg = partes[1].strip() if len(partes) > 1 else ""
        est = self.ventana_estado
        canal_actual = v.nombre if v is not None and v.tipo == "canal" else ""

        # Alias definidos por el usuario
        if cmd in self.cfg["aliases"] and cmd not in COMANDOS_INTERNOS:
            if profundidad >= 5:
                est.escribir(f"El alias /{cmd} se llama a sí mismo demasiadas veces.", "aviso")
                return
            destino = v.nombre if v is not None and v.tipo != "estado" else ""
            for sub in expandir_alias(self.cfg["aliases"][cmd], arg, self.nick, destino):
                self.ejecutar(sub, v, profundidad + 1)
            return

        if cmd in NECESITAN_RED and not self.irc.activo:
            est.escribir("No estás conectado.", "aviso")
            return

        if cmd == "join":
            if not arg:
                est.escribir("Uso: /join #canal [clave]", "aviso")
                return
            if not arg.startswith("#"):
                arg = "#" + arg
            self.irc.enviar(f"JOIN {arg}")
        elif cmd == "part":
            canal, motivo = canal_actual, arg
            if arg.startswith("#"):
                canal, _, motivo = arg.partition(" ")
            if canal:
                self.irc.enviar(f"PART {canal}" + (f" :{motivo}" if motivo else ""))
        elif cmd == "msg":
            destino, _, texto = arg.partition(" ")
            if not destino or not texto.strip():
                est.escribir("Uso: /msg nick_o_#canal mensaje", "aviso")
                return
            self.irc.enviar(f"PRIVMSG {destino} :{texto}")
            if destino.startswith("#"):
                w = self.ventanas.get(destino.lower())
            else:
                w = self.obtener_ventana(destino, "privado", seleccionar=True)
            (w or est).escribir_chat(self.nick, texto, propio=True)
        elif cmd == "notice":
            destino, _, texto = arg.partition(" ")
            if destino and texto.strip():
                self.irc.enviar(f"NOTICE {destino} :{texto}")
                (v or est).escribir(f"-> -{destino}- {texto}", "aviso")
            else:
                est.escribir("Uso: /notice nick_o_#canal mensaje", "aviso")
        elif cmd == "query":
            if arg:
                self.obtener_ventana(arg.split()[0], "privado", seleccionar=True)
        elif cmd == "nick":
            if arg:
                self.irc.enviar(f"NICK {arg.split()[0]}")
        elif cmd == "me":
            if v is None or v.tipo == "estado" or not arg:
                est.escribir("Uso: /me acción (dentro de un canal o chat privado)", "aviso")
                return
            self.irc.enviar(f"PRIVMSG {v.nombre} :\x01ACTION {arg}\x01")
            v.escribir(f"* {self.nick} {arg}", "accion")
        elif cmd == "topic":
            if not canal_actual:
                est.escribir("Usa /topic dentro de un canal.", "aviso")
            elif arg:
                self.irc.enviar(f"TOPIC {canal_actual} :{arg}")
            else:
                self.irc.enviar(f"TOPIC {canal_actual}")
        elif cmd == "whois":
            if arg:
                self.ultimo_whois = v
                self.irc.enviar(f"WHOIS {arg.split()[0]}")
        elif cmd == "away":
            self.irc.enviar(f"AWAY :{arg}" if arg else "AWAY")
        elif cmd == "kick":
            nick, _, razon = arg.partition(" ")
            if canal_actual and nick:
                self.irc.enviar(f"KICK {canal_actual} {nick}" + (f" :{razon}" if razon else ""))
            else:
                est.escribir("Uso: /kick nick [motivo] (dentro de un canal)", "aviso")
        elif cmd == "mode":
            if arg:
                objetivo = arg if arg[0] in "#&" or not canal_actual else f"{canal_actual} {arg}"
                self.irc.enviar(f"MODE {objetivo}")
        elif cmd == "quit":
            self.irc.desconectar(arg or self.cfg["mensaje_quit"])
        elif cmd == "raw":
            self.irc.enviar(arg)
        elif cmd == "close":
            self.cerrar_ventana(v)
        elif cmd == "clear":
            if v is not None:
                v.limpiar()
        elif cmd in ("ayuda", "help"):
            for linea_ayuda in (
                "Canales: /join #canal · /part [#canal] · /topic [texto] · /kick nick [motivo] · /mode ...",
                "Mensajes: /msg nick texto · /query nick · /notice destino texto · /me acción",
                "Cuenta: /nick nuevo · /away [motivo] · /whois nick · /quit [motivo]",
                "Ventana: /clear · /close · /raw LÍNEA",
                "Tus alias: " + (", ".join("/" + a for a in sorted(self.cfg["aliases"])) or "(ninguno)"),
                "Atajos: Ctrl+O preferencias · Ctrl+J entrar a canal · Tab autocompleta nicks · ↑/↓ historial",
            ):
                est.escribir(linea_ayuda, "sistema")
        else:
            est.escribir(f"Comando desconocido: /{cmd}. Escribe /ayuda", "aviso")

    # ---------- Eventos del servidor ----------
    def revisar_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                self._atender(tipo, dato)
        except queue.Empty:
            pass
        finally:
            try:
                self.after(100, self.revisar_cola)
            except tk.TclError:
                pass

    def _atender(self, tipo, dato):
        est = self.ventana_estado
        if tipo == "linea":
            try:
                self.procesar(dato)
            except Exception as e:  # una línea rara no debe tumbar el cliente
                est.escribir(f"[error interno] {e} :: {dato[:120]}", "aviso")
        elif tipo == "conectado":
            est.escribir("Conexión establecida.", "sistema")
        elif tipo == "error":
            est.escribir(f"Error de conexión: {dato}", "aviso")
            if "CERTIFICATE_VERIFY_FAILED" in dato:
                est.escribir("Pista: revisa «Nombre del certificado» en Preferencias > Servidores.", "aviso")
        elif tipo == "cerrado":
            self.registrado = False
            self.estado_var.set("○ Desconectado")
            self.btn_conexion.configure(text="Conectar")
            for v in list(self.ventanas.values()):
                v.escribir("Desconectado del servidor.", "aviso")
                v.usuarios.clear()
                v.refrescar_usuarios()
        elif tipo == "act_info":
            self._resultado_busqueda(*dato)
        elif tipo == "act_error":
            mensaje, silencioso = dato
            est.escribir(f"Actualización: {mensaje}", "aviso")
            if not silencioso:
                messagebox.showerror("Actualizaciones", mensaje, parent=self)
        elif tipo == "act_listo":
            self.aplicar_actualizacion(dato)

    def es_yo(self, nick):
        return nick.lower() == self.nick.lower()

    def ejecutar_perform(self):
        for linea in self.cfg["perform"]:
            self.ejecutar(linea, self.ventana_estado)

    def procesar(self, texto):
        prefijo, cmd, p = parsear(texto)
        origen = prefijo.split("!")[0]
        host = prefijo.partition("!")[2]
        est = self.ventana_estado

        if cmd == "001":
            self.registrado = True
            self.nick = p[0]
            est.escribir(p[-1], "sistema")
            self._estado_conectado()
            self.after(600, self.ejecutar_perform)

        elif cmd == "433":
            if not self.registrado:
                alt = self.cfg["nick_alt"].strip()
                if alt and alt != self.nick and self.nick == self.cfg["nick"]:
                    self.nick = alt
                else:
                    self.nick += "_"
                est.escribir(f"Ese nick está en uso; probando {self.nick}", "aviso")
                self.irc.enviar(f"NICK {self.nick}")
            else:
                est.escribir(" ".join(p[1:]), "aviso")

        elif cmd == "JOIN":
            canal = p[0]
            if self.es_yo(origen):
                v = self.obtener_ventana(canal, "canal", seleccionar=True)
                v.usuarios.clear()
                v.refrescar_usuarios()
                v.escribir(f"Entraste a {canal}", "sistema")
            else:
                v = self.ventanas.get(canal.lower())
                if v:
                    v.usuarios[origen] = ""
                    v.refrescar_usuarios()
                    v.escribir(f"→ {origen} ({host}) entró", "sistema")

        elif cmd == "PART":
            v = self.ventanas.get(p[0].lower())
            if self.es_yo(origen):
                self.cerrar_ventana(v, enviar_part=False)
            elif v:
                v.usuarios.pop(origen, None)
                v.refrescar_usuarios()
                motivo = f" ({p[1]})" if len(p) > 1 and p[1] else ""
                v.escribir(f"← {origen} salió{motivo}", "sistema")

        elif cmd == "QUIT":
            motivo = f" ({p[0]})" if p and p[0] else ""
            for v in list(self.ventanas.values()):
                if origen in v.usuarios:
                    v.usuarios.pop(origen)
                    v.refrescar_usuarios()
                    v.escribir(f"← {origen} se fue{motivo}", "sistema")

        elif cmd == "KICK":
            v = self.ventanas.get(p[0].lower())
            victima = p[1]
            razon = p[2] if len(p) > 2 else ""
            if v:
                v.escribir(f"{victima} fue expulsado por {origen} ({razon})", "aviso")
                if self.es_yo(victima):
                    v.usuarios.clear()
                else:
                    v.usuarios.pop(victima, None)
                v.refrescar_usuarios()

        elif cmd == "NICK":
            nuevo = p[0]
            if self.es_yo(origen):
                self.nick = nuevo
                est.escribir(f"Ahora eres {nuevo}", "sistema")
                self._estado_conectado()
            for v in list(self.ventanas.values()):
                if origen in v.usuarios:
                    v.usuarios[nuevo] = v.usuarios.pop(origen)
                    v.refrescar_usuarios()
                    v.escribir(f"{origen} ahora es {nuevo}", "sistema")

        elif cmd == "PRIVMSG":
            if len(p) < 2:
                return
            destino, mensaje = p[0], p[1]
            accion = mensaje.startswith("\x01ACTION ")
            if mensaje.startswith("\x01") and not accion:
                return  # otros mensajes CTCP: se ignoran por ahora
            if accion:
                mensaje = mensaje[8:].rstrip("\x01")
            if destino.startswith("#"):
                v = self.ventanas.get(destino.lower()) or est
            else:
                v = self.obtener_ventana(origen, "privado")
            if accion:
                v.escribir(f"* {origen} {mensaje}", "accion")
            else:
                v.escribir_chat(origen, mensaje, resaltar=self.nick.lower() in mensaje.lower())

        elif cmd == "NOTICE":
            destino, mensaje = p[0], p[-1]
            v = self.ventanas.get(destino.lower()) if destino.startswith("#") else None
            (v or est).escribir(f"-{origen or 'servidor'}- {mensaje}", "aviso")

        elif cmd == "332":
            v = self.ventanas.get(p[1].lower())
            if v:
                v.tema_var.set(p[2])
                v.escribir(f"Tema: {p[2]}", "sistema")

        elif cmd == "TOPIC":
            v = self.ventanas.get(p[0].lower())
            if v:
                v.tema_var.set(p[1])
                v.escribir(f"{origen} cambió el tema: {p[1]}", "sistema")

        elif cmd == "353":   # lista de usuarios (llega en bloques)
            lista = self.pendientes.setdefault(p[2].lower(), {})
            for n in p[3].split():
                pref = n[0] if n[0] in PREFIJOS else ""
                lista[n.lstrip(PREFIJOS)] = pref

        elif cmd == "366":   # fin de la lista de usuarios
            canal = p[1].lower()
            datos = self.pendientes.pop(canal, None)
            v = self.ventanas.get(canal)
            if v and datos is not None:
                v.usuarios = datos
                v.refrescar_usuarios()

        elif cmd == "MODE":
            if p[0].startswith("#"):
                v = self.ventanas.get(p[0].lower())
                if v:
                    v.escribir(f"* {origen} pone modo {' '.join(p[1:])}", "sistema")
                if len(p) > 2:
                    self.irc.enviar(f"NAMES {p[0]}")  # refresca @/+ de la lista
            else:
                est.escribir(f"Modo de usuario: {' '.join(p[1:])}", "sistema")

        elif cmd == "ERROR":
            est.escribir(p[-1] if p else texto, "aviso")

        elif cmd.isdigit():
            destino = est
            w = self.ultimo_whois
            if cmd in NUM_WHOIS and w is not None and self.ventanas.get(w.nombre.lower()) is w:
                destino = w
            destino.escribir(" ".join(p[1:]), "aviso" if cmd[0] in "45" else "")

        else:
            est.escribir(texto, "sistema")

    # ---------- Actualizaciones ----------
    def buscar_actualizacion(self, url=None, silencioso=False):
        url = (url if url is not None else self.cfg["url_actualizacion"]).strip()
        if not url:
            if not silencioso:
                messagebox.showinfo("Actualizaciones",
                                    "Aún no has configurado la dirección de actualización.\n"
                                    "Ve a Conexión > Preferencias > Actualización.", parent=self)
            return
        if not url.lower().startswith("https://"):
            if not silencioso:
                messagebox.showwarning("Actualizaciones", "La dirección debe empezar con https://", parent=self)
            return
        threading.Thread(target=self._hilo_buscar, args=(url, silencioso), daemon=True).start()

    def _hilo_buscar(self, url, silencioso):
        try:
            peticion = urllib.request.Request(url, headers={"User-Agent": f"MiClienteIRC/{VERSION}"})
            with urllib.request.urlopen(peticion, timeout=15) as r:
                datos = json.loads(r.read(1_000_000).decode("utf-8"))
            if not isinstance(datos, dict) or "version" not in datos or "url" not in datos:
                raise ValueError("El archivo de actualización no tiene el formato esperado.")
            self.cola.put(("act_info", (datos, silencioso)))
        except Exception as e:
            self.cola.put(("act_error", (f"No se pudo comprobar: {e}", silencioso)))

    def _resultado_busqueda(self, datos, silencioso):
        nueva = str(datos["version"])
        if version_tupla(nueva) <= version_tupla(VERSION):
            if not silencioso:
                messagebox.showinfo("Actualizaciones", f"Ya tienes la última versión ({VERSION}).", parent=self)
            return
        notas = str(datos.get("notas", ""))[:600]
        aviso = "" if datos.get("sha256") else "\n\n⚠ Esta actualización no incluye huella SHA-256 para verificarla."
        if messagebox.askyesno("Actualización disponible",
                               f"Hay una versión nueva: {nueva} (tienes {VERSION}).\n\n{notas}{aviso}\n\n"
                               "¿Descargarla ahora?", parent=self):
            self.descargar_actualizacion(datos)

    def descargar_actualizacion(self, datos):
        url = str(datos["url"])
        if not url.lower().startswith("https://"):
            messagebox.showerror("Actualizaciones", "La descarga debe ser por https://", parent=self)
            return
        if not getattr(sys, "frozen", False) or os.name != "nt":
            webbrowser.open(url)
            messagebox.showinfo("Actualizaciones",
                                "Estás ejecutando el código con Python, así que abrí la descarga en tu navegador.",
                                parent=self)
            return
        self.ventana_estado.escribir("Descargando actualización…", "sistema")
        threading.Thread(target=self._hilo_descarga, args=(url, str(datos.get("sha256", ""))), daemon=True).start()

    def _hilo_descarga(self, url, sha256):
        destino = os.path.join(config.carpeta_config(), "MiClienteIRC_nuevo.exe")
        try:
            h = hashlib.sha256()
            total = 0
            peticion = urllib.request.Request(url, headers={"User-Agent": f"MiClienteIRC/{VERSION}"})
            with urllib.request.urlopen(peticion, timeout=30) as r, open(destino, "wb") as f:
                while True:
                    bloque = r.read(65536)
                    if not bloque:
                        break
                    total += len(bloque)
                    if total > 300 * 1024 * 1024:
                        raise ValueError("el archivo es demasiado grande")
                    h.update(bloque)
                    f.write(bloque)
            with open(destino, "rb") as f:
                if f.read(2) != b"MZ":
                    raise ValueError("el archivo descargado no es un ejecutable de Windows")
            if sha256.strip() and h.hexdigest().lower() != sha256.strip().lower():
                raise ValueError("la verificación SHA-256 falló: el archivo no coincide")
            self.cola.put(("act_listo", destino))
        except Exception as e:
            try:
                os.remove(destino)
            except OSError:
                pass
            self.cola.put(("act_error", (f"No se pudo descargar: {e}", False)))

    def aplicar_actualizacion(self, nuevo):
        actual = sys.executable
        bat = os.path.join(config.carpeta_config(), "actualizar.bat")
        script = (
            "@echo off\r\n"
            "set intentos=0\r\n"
            ":esperar\r\n"
            "set /a intentos+=1\r\n"
            "ping 127.0.0.1 -n 3 >nul\r\n"
            f'move /y "{nuevo}" "{actual}" >nul 2>&1\r\n'
            "if errorlevel 1 if %intentos% LSS 20 goto esperar\r\n"
            f'start "" "{actual}"\r\n'
            'del "%~f0"\r\n'
        )
        try:
            with open(bat, "w", encoding="oem", errors="replace", newline="") as f:
                f.write(script)
            entorno = {k: val for k, val in os.environ.items()
                       if not (k.startswith("_MEI") or k.startswith("_PYI"))}
            messagebox.showinfo("Actualización lista",
                                "La actualización se descargó. El programa se cerrará y volverá a abrirse solo.",
                                parent=self)
            subprocess.Popen(["cmd", "/c", bat], env=entorno, close_fds=True,
                             creationflags=0x08000000 | 0x00000200)
            self.cerrar_app()
        except OSError as e:
            messagebox.showerror("Actualizaciones", f"No se pudo aplicar la actualización: {e}", parent=self)


if __name__ == "__main__":
    App().mainloop()
