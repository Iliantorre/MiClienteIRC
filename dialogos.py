"""Cuadro de Preferencias, al estilo de las opciones de mIRC pero más limpio."""
import copy
import re
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import config
from config import COMANDOS_INTERNOS, VERSION

FORMATOS_HORA = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%d/%m %H:%M", "%d/%m/%Y %H:%M:%S")


class Preferencias(tk.Toplevel):
    def __init__(self, app, cfg, al_guardar, buscar, pestana=0):
        super().__init__(app)
        self.app = app
        self.cfg = cfg
        self.al_guardar = al_guardar
        self.buscar = buscar
        self.t = app.tema()
        self.fuente = (cfg["fuente"], cfg["tamano"])

        self.title("Preferencias")
        self.configure(bg=self.t["bg"])
        self.transient(app)
        self.geometry(f"720x540+{app.winfo_rootx() + 50}+{app.winfo_rooty() + 40}")
        self.minsize(660, 500)

        # Copias de trabajo: nada se aplica hasta pulsar "Guardar"
        self.servidores = copy.deepcopy(cfg["servidores"])
        self.activo = cfg["servidor_activo"]
        self.aliases = dict(cfg["aliases"])
        self.idx_serv = None

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self._pestana_identidad()
        self._pestana_servidores()
        self._pestana_apariencia()
        self._pestana_alias()
        self._pestana_conexion()
        self._pestana_actualizacion()
        self.nb.select(min(pestana, len(self.nb.tabs()) - 1))

        barra = ttk.Frame(self)
        barra.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(barra, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(barra, text="Guardar", command=self.guardar).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ---------- utilidades ----------
    def _pestana(self, titulo):
        marco = ttk.Frame(self.nb, padding=18)
        self.nb.add(marco, text=titulo)
        return marco

    def _lista(self, padre, ancho):
        lb = tk.Listbox(padre, width=ancho, exportselection=False, font=self.fuente,
                        bg=self.t["campo"], fg=self.t["campo_fg"],
                        selectbackground=self.t["acento"], selectforeground="#ffffff",
                        relief="flat", highlightthickness=0, activestyle="none")
        return lb

    def _filas(self, marco, campos):
        for i, (texto, var, kw) in enumerate(campos):
            ttk.Label(marco, text=texto).grid(row=i, column=0, sticky="w", pady=6)
            ttk.Entry(marco, textvariable=var, **kw).grid(
                row=i, column=1, sticky="ew", padx=(14, 0), pady=6)
        marco.columnconfigure(1, weight=1)

    # ---------- Identidad ----------
    def _pestana_identidad(self):
        f = self._pestana("Identidad")
        self.v_nick = tk.StringVar(value=self.cfg["nick"])
        self.v_nick_alt = tk.StringVar(value=self.cfg["nick_alt"])
        self.v_usuario = tk.StringVar(value=self.cfg["usuario"])
        self.v_real = tk.StringVar(value=self.cfg["nombre_real"])
        self.v_quit = tk.StringVar(value=self.cfg["mensaje_quit"])
        self._filas(f, [
            ("Nick (apodo)", self.v_nick, {}),
            ("Nick alternativo", self.v_nick_alt, {}),
            ("ID de usuario (ident)", self.v_usuario, {}),
            ("Nombre real", self.v_real, {}),
            ("Mensaje al salir", self.v_quit, {}),
        ])
        ttk.Label(f, wraplength=560, justify="left",
                  text="El nick alternativo se usa si el principal ya está ocupado. "
                       "Los cambios de identidad se aplican la próxima vez que te conectes."
                  ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(16, 0))

    # ---------- Servidores ----------
    def _pestana_servidores(self):
        f = self._pestana("Servidores")
        izq = ttk.Frame(f)
        izq.pack(side="left", fill="y")
        self.lista_serv = self._lista(izq, 24)
        self.lista_serv.pack(fill="both", expand=True)
        self.lista_serv.bind("<<ListboxSelect>>", self._al_elegir_servidor)
        fila = ttk.Frame(izq)
        fila.pack(fill="x", pady=(8, 0))
        ttk.Button(fila, text="Nuevo", command=self._nuevo_servidor).pack(side="left")
        ttk.Button(fila, text="Eliminar", command=self._eliminar_servidor).pack(side="left", padx=(6, 0))

        der = ttk.Frame(f, padding=(18, 0, 0, 0))
        der.pack(side="left", fill="both", expand=True)
        self.s_nombre = tk.StringVar()
        self.s_host = tk.StringVar()
        self.s_puerto = tk.StringVar()
        self.s_tls = tk.BooleanVar(value=True)
        self.s_tls_nombre = tk.StringVar()
        self.s_clave = tk.StringVar()
        self._filas(der, [
            ("Nombre", self.s_nombre, {}),
            ("Servidor", self.s_host, {}),
            ("Puerto", self.s_puerto, {"width": 8}),
        ])
        ttk.Checkbutton(der, text="Usar conexión segura (TLS)", variable=self.s_tls).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Label(der, text="Nombre del certificado").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(der, textvariable=self.s_tls_nombre).grid(row=4, column=1, sticky="ew", padx=(14, 0))
        ttk.Label(der, text="Contraseña del servidor").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(der, textvariable=self.s_clave, show="•").grid(row=5, column=1, sticky="ew", padx=(14, 0))
        ttk.Label(der, wraplength=330, justify="left",
                  text="«Nombre del certificado» solo hace falta si el certificado del servidor "
                       "está emitido para otro nombre (como en ChatZona). Déjalo vacío si no."
                  ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 10))
        fila2 = ttk.Frame(der)
        fila2.grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(fila2, text="Aplicar cambios", command=self._aplicar_servidor).pack(side="left")
        ttk.Button(fila2, text="★ Usar este servidor", command=self._usar_servidor).pack(side="left", padx=(8, 0))

        self._refrescar_servidores(self.activo)

    def _refrescar_servidores(self, seleccionar=None):
        self.lista_serv.delete(0, "end")
        for i, s in enumerate(self.servidores):
            self.lista_serv.insert("end", ("★ " if i == self.activo else "   ") + s["nombre"])
        if seleccionar is not None and 0 <= seleccionar < len(self.servidores):
            self.lista_serv.selection_clear(0, "end")
            self.lista_serv.selection_set(seleccionar)
            self.lista_serv.see(seleccionar)
            self._cargar_servidor(seleccionar)

    def _al_elegir_servidor(self, evento=None):
        sel = self.lista_serv.curselection()
        if sel:
            self._cargar_servidor(sel[0])

    def _cargar_servidor(self, i):
        self.idx_serv = i
        s = self.servidores[i]
        self.s_nombre.set(s["nombre"])
        self.s_host.set(s["host"])
        self.s_puerto.set(str(s["puerto"]))
        self.s_tls.set(s["tls"])
        self.s_tls_nombre.set(s["tls_nombre"])
        self.s_clave.set(s["clave"])

    def _aplicar_servidor(self):
        """Pasa el formulario al servidor seleccionado. Devuelve True si fue válido."""
        i = self.idx_serv
        if i is None:
            return True
        host = self.s_host.get().strip()
        if not host or " " in host:
            messagebox.showerror("Servidor", "Escribe una dirección de servidor válida.", parent=self)
            return False
        try:
            puerto = int(self.s_puerto.get())
            if not 1 <= puerto <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Servidor", "El puerto debe ser un número entre 1 y 65535.", parent=self)
            return False
        self.servidores[i] = {
            "nombre": self.s_nombre.get().strip() or host,
            "host": host,
            "puerto": puerto,
            "tls": bool(self.s_tls.get()),
            "tls_nombre": self.s_tls_nombre.get().strip(),
            "clave": self.s_clave.get(),
        }
        self._refrescar_servidores(i)
        return True

    def _nuevo_servidor(self):
        self.servidores.append({"nombre": "Nuevo servidor", "host": "", "puerto": 6697,
                                "tls": True, "tls_nombre": "", "clave": ""})
        self._refrescar_servidores(len(self.servidores) - 1)

    def _eliminar_servidor(self):
        i = self.idx_serv
        if i is None:
            return
        if len(self.servidores) == 1:
            messagebox.showinfo("Servidores", "Debe quedar al menos un servidor en la lista.", parent=self)
            return
        del self.servidores[i]
        if i < self.activo:
            self.activo -= 1
        elif i == self.activo:
            self.activo = 0
        self.idx_serv = None
        self._refrescar_servidores(min(i, len(self.servidores) - 1))

    def _usar_servidor(self):
        if self.idx_serv is None or not self._aplicar_servidor():
            return
        self.activo = self.idx_serv
        self._refrescar_servidores(self.idx_serv)

    # ---------- Apariencia ----------
    def _pestana_apariencia(self):
        f = self._pestana("Apariencia")
        self.v_tema = tk.StringVar(value=self.cfg["tema"])
        self.v_fuente = tk.StringVar(value=self.cfg["fuente"])
        self.v_tamano = tk.StringVar(value=str(self.cfg["tamano"]))
        self.v_mostrar_hora = tk.BooleanVar(value=self.cfg["mostrar_hora"])
        self.v_formato = tk.StringVar(value=self.cfg["formato_hora"])
        self.v_vista = tk.StringVar()
        self.v_modo = tk.StringVar(value=self.cfg["modo_ventanas"])

        ttk.Label(f, text="Tema").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=self.v_tema, state="readonly",
                     values=list(config.TEMAS)).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(f, text="Fuente").grid(row=1, column=0, sticky="w", pady=6)
        familias = sorted({x for x in tkfont.families(self.app) if not x.startswith("@")})
        ttk.Combobox(f, textvariable=self.v_fuente, values=familias, width=30).grid(
            row=1, column=1, sticky="w", padx=(14, 0))
        ttk.Label(f, text="Tamaño").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Spinbox(f, from_=8, to=24, textvariable=self.v_tamano, width=6).grid(
            row=2, column=1, sticky="w", padx=(14, 0))

        ttk.Separator(f).grid(row=3, column=0, columnspan=2, sticky="ew", pady=12)

        ttk.Checkbutton(f, text="Mostrar la hora en cada mensaje", variable=self.v_mostrar_hora).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(f, text="Formato de fecha/hora").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=self.v_formato, values=FORMATOS_HORA, width=22).grid(
            row=5, column=1, sticky="w", padx=(14, 0))
        ttk.Label(f, text="Vista previa").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Label(f, textvariable=self.v_vista).grid(row=6, column=1, sticky="w", padx=(14, 0))
        self.v_formato.trace_add("write", self._actualizar_vista)
        self._actualizar_vista()

        ttk.Separator(f).grid(row=7, column=0, columnspan=2, sticky="ew", pady=12)

        ttk.Label(f, text="Canales y privados").grid(row=8, column=0, sticky="nw", pady=4)
        marco = ttk.Frame(f)
        marco.grid(row=8, column=1, sticky="w", padx=(14, 0))
        ttk.Radiobutton(marco, text="Pestañas dentro de una sola ventana",
                        variable=self.v_modo, value="pestanas").pack(anchor="w")
        ttk.Radiobutton(marco, text="Ventanas separadas (una por canal, como mIRC)",
                        variable=self.v_modo, value="ventanas").pack(anchor="w", pady=(4, 0))
        ttk.Label(f, wraplength=560, justify="left",
                  text="El tema y la fuente se aplican al guardar. El modo de ventanas afecta "
                       "a los canales que abras desde ese momento."
                  ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _actualizar_vista(self, *args):
        try:
            self.v_vista.set(time.strftime(self.v_formato.get()))
        except ValueError:
            self.v_vista.set("(formato no válido)")

    # ---------- Alias ----------
    def _pestana_alias(self):
        f = self._pestana("Alias")
        izq = ttk.Frame(f)
        izq.pack(side="left", fill="y")
        self.lista_alias = self._lista(izq, 26)
        self.lista_alias.pack(fill="both", expand=True)
        self.lista_alias.bind("<<ListboxSelect>>", self._al_elegir_alias)

        der = ttk.Frame(f, padding=(18, 0, 0, 0))
        der.pack(side="left", fill="both", expand=True)
        self.a_nombre = tk.StringVar()
        self.a_cmd = tk.StringVar()
        ttk.Label(der, text="Alias (sin la barra)").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(der, textvariable=self.a_nombre, width=16).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(der, text="Comando(s)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(der, textvariable=self.a_cmd).grid(row=1, column=1, sticky="ew", padx=(14, 0))
        der.columnconfigure(1, weight=1)
        fila = ttk.Frame(der)
        fila.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 10))
        ttk.Button(fila, text="Guardar alias", command=self._guardar_alias).pack(side="left")
        ttk.Button(fila, text="Eliminar", command=self._eliminar_alias).pack(side="left", padx=(8, 0))
        ttk.Label(der, wraplength=330, justify="left", text=(
            "Variables: $1 $2 … son las palabras que escribes después del alias; "
            "$2- es «desde la segunda hasta el final»; $me es tu nick y $chan el canal actual. "
            "Usa | para ejecutar varios comandos.\n\n"
            "Ejemplo: alias «hola» = /msg $1 hola, ¿cómo estás? | /me saluda a $1\n"
            "Se usa escribiendo: /hola Ana")
        ).grid(row=3, column=0, columnspan=2, sticky="w")
        self._refrescar_alias()

    def _refrescar_alias(self, seleccionar=None):
        self.lista_alias.delete(0, "end")
        nombres = sorted(self.aliases)
        for n in nombres:
            self.lista_alias.insert("end", f"/{n}")
        if seleccionar in nombres:
            i = nombres.index(seleccionar)
            self.lista_alias.selection_set(i)
            self.lista_alias.see(i)

    def _al_elegir_alias(self, evento=None):
        sel = self.lista_alias.curselection()
        if sel:
            nombre = self.lista_alias.get(sel[0]).lstrip("/")
            self.a_nombre.set(nombre)
            self.a_cmd.set(self.aliases.get(nombre, ""))

    def _guardar_alias(self):
        nombre = self.a_nombre.get().strip().lstrip("/").lower()
        cmd = self.a_cmd.get().strip()
        if not re.match(r"^[a-z0-9_]{1,20}$", nombre):
            messagebox.showerror("Alias", "El nombre solo puede tener letras, números y _ (máximo 20).", parent=self)
            return
        if nombre in COMANDOS_INTERNOS:
            messagebox.showerror("Alias", f"«{nombre}» ya es un comando del cliente; elige otro nombre.", parent=self)
            return
        if not cmd:
            messagebox.showerror("Alias", "Escribe el comando que ejecutará el alias.", parent=self)
            return
        self.aliases[nombre] = cmd
        self._refrescar_alias(nombre)

    def _eliminar_alias(self):
        nombre = self.a_nombre.get().strip().lstrip("/").lower()
        if nombre in self.aliases:
            del self.aliases[nombre]
            self.a_nombre.set("")
            self.a_cmd.set("")
            self._refrescar_alias()

    # ---------- Al conectar ----------
    def _pestana_conexion(self):
        f = self._pestana("Al conectar")
        self.v_auto = tk.BooleanVar(value=self.cfg["autoconectar"])
        ttk.Checkbutton(f, text="Conectar automáticamente al abrir el programa",
                        variable=self.v_auto).pack(anchor="w")
        ttk.Label(f, wraplength=620, justify="left", text=(
            "Comandos que se ejecutan al conectarte (uno por línea), por ejemplo:\n"
            "/join #micanal\n/msg NickServ identify tu_clave")).pack(anchor="w", pady=(14, 6))
        self.txt_perform = tk.Text(f, height=10, font=self.fuente, wrap="none",
                                   bg=self.t["campo"], fg=self.t["campo_fg"],
                                   insertbackground=self.t["campo_fg"], relief="flat",
                                   highlightthickness=0, padx=8, pady=6)
        self.txt_perform.pack(fill="both", expand=True)
        self.txt_perform.insert("1.0", "\n".join(self.cfg["perform"]))
        ttk.Label(f, wraplength=620, justify="left", foreground=self.t["aviso"],
                  text="Ojo: lo que escribas aquí (incluidas contraseñas) se guarda sin cifrar "
                       "en el archivo de configuración de tu usuario."
                  ).pack(anchor="w", pady=(8, 0))

    # ---------- Actualización ----------
    def _pestana_actualizacion(self):
        f = self._pestana("Actualización")
        self.v_url = tk.StringVar(value=self.cfg["url_actualizacion"])
        self.v_inicio = tk.BooleanVar(value=self.cfg["buscar_al_inicio"])
        ttk.Label(f, text=f"Versión instalada: {VERSION}").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(f, text="Dirección (https)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.v_url).grid(row=1, column=1, sticky="ew", padx=(14, 0))
        f.columnconfigure(1, weight=1)
        ttk.Checkbutton(f, text="Buscar actualizaciones al abrir el programa",
                        variable=self.v_inicio).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(f, text="Buscar ahora", command=lambda: self.buscar(url=self.v_url.get())).grid(
            row=3, column=0, sticky="w", pady=(6, 14))
        ttk.Label(f, wraplength=620, justify="left", text=(
            "La dirección debe apuntar a un archivo JSON que tú publiques, con este formato:\n\n"
            '{"version": "1.2.0", "url": "https://tusitio.com/MiClienteIRC.exe",\n'
            ' "sha256": "huella del .exe (recomendado)", "notas": "Qué cambió"}\n\n'
            "Cuando publiques una versión nueva, sube el .exe, actualiza ese JSON y los "
            "programas instalados lo detectarán. La instalación automática solo funciona "
            "con el .exe; si ejecutas el código con Python, se abre la descarga en el navegador.")
        ).grid(row=4, column=0, columnspan=2, sticky="w")

    # ---------- Guardar ----------
    def guardar(self):
        nick = self.v_nick.get().strip()
        alt = self.v_nick_alt.get().strip()
        usuario = self.v_usuario.get().strip()
        if not nick or " " in nick or not usuario or " " in usuario or " " in alt:
            messagebox.showerror("Identidad", "El nick y el ID de usuario no pueden estar vacíos "
                                 "ni llevar espacios.", parent=self)
            self.nb.select(0)
            return
        if not self._aplicar_servidor():
            self.nb.select(1)
            return
        formato = self.v_formato.get().strip() or "%H:%M"
        try:
            time.strftime(formato)
        except ValueError:
            messagebox.showerror("Apariencia", "El formato de fecha/hora no es válido.", parent=self)
            self.nb.select(2)
            return
        try:
            tamano = int(self.v_tamano.get())
        except ValueError:
            tamano = 10

        self.cfg.update({
            "nick": nick,
            "nick_alt": alt,
            "usuario": usuario,
            "nombre_real": self.v_real.get().strip() or "Mi cliente IRC",
            "mensaje_quit": self.v_quit.get().strip(),
            "servidores": self.servidores,
            "servidor_activo": self.activo,
            "tema": self.v_tema.get(),
            "fuente": self.v_fuente.get().strip() or "Segoe UI",
            "tamano": tamano,
            "mostrar_hora": bool(self.v_mostrar_hora.get()),
            "formato_hora": formato,
            "modo_ventanas": self.v_modo.get(),
            "aliases": self.aliases,
            "autoconectar": bool(self.v_auto.get()),
            "perform": [x.strip() for x in self.txt_perform.get("1.0", "end").splitlines() if x.strip()],
            "url_actualizacion": self.v_url.get().strip(),
            "buscar_al_inicio": bool(self.v_inicio.get()),
        })
        config.validar(self.cfg)
        try:
            config.guardar(self.cfg)
        except OSError as e:
            messagebox.showwarning("Preferencias", f"No se pudo guardar el archivo de configuración:\n{e}", parent=self)
        self.al_guardar()
        self.destroy()
