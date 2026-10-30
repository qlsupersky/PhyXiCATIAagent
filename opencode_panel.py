"""General OpenCode chat page, separate from the optional structured macro workflow."""
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageGrab, ImageTk
from opencode_link import OpenCodeLink, read_attachment


class OpenCodePage:
    def __init__(self, panel, parent, config):
        self.panel, self.root = panel, panel.root
        self.link = OpenCodeLink(panel.controller.workspace, config.get('opencode_project'))
        self.attachments = []
        self.catalog = {'models': [], 'agents': [], 'commands': []}
        self.session_map = {}
        self.photos = []
        ttk.Label(parent, text='OpenCode 图文对话', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(parent, text='连接同一个 OpenCode 服务与会话 · 支持图片、连续对话和工具调用', wraplength=950).pack(anchor='w', pady=4)
        top = ttk.Frame(parent); top.pack(fill='x')
        panel.button(top, '连接 / 刷新', self.connect).pack(side='left')
        panel.button(top, '新对话', self.new).pack(side='left', padx=4)
        ttk.Button(top, text='完整 OpenCode 界面', command=self.full).pack(side='left')
        panel.button(top, '选择项目…', self.project).pack(side='left', padx=4)
        self.status = tk.StringVar(value='尚未连接 · 项目：' + str(self.link.project))
        ttk.Label(parent, textvariable=self.status, wraplength=950).pack(anchor='w', pady=4)
        choices = ttk.Frame(parent); choices.pack(fill='x')
        self.session_value = tk.StringVar()
        self.sessions = ttk.Combobox(choices, textvariable=self.session_value, state='readonly', width=48)
        self.sessions.pack(side='left', fill='x', expand=True)
        self.sessions.bind('<<ComboboxSelected>>', self.load)
        choices = ttk.Frame(parent); choices.pack(fill='x', pady=3)
        self.model = tk.StringVar(value='沿用会话 / OpenCode 默认')
        self.models = ttk.Combobox(choices, textvariable=self.model, state='readonly', width=34)
        self.models.pack(side='left', padx=4, fill='x', expand=True)
        self.models.bind('<<ComboboxSelected>>', self.update_variants)
        self.agent = tk.StringVar(value='沿用会话 Agent')
        self.agents = ttk.Combobox(choices, textvariable=self.agent, state='readonly', width=18)
        self.agents.pack(side='left')
        self.variant = tk.StringVar(value='沿用模型变体')
        self.variants = ttk.Combobox(choices, textvariable=self.variant, state='readonly', width=18)
        self.variants.pack(side='left', padx=4)
        composer = ttk.Frame(parent); composer.pack(side='bottom', fill='x')
        box = ttk.Frame(parent); box.pack(fill='both', expand=True, pady=6)
        self.output = tk.Text(box, height=4, wrap='word', state='disabled', font=('Microsoft YaHei UI', 10))
        scroll = ttk.Scrollbar(box, command=self.output.yview); scroll.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=scroll.set); self.output.pack(fill='both', expand=True)
        row = ttk.Frame(composer); row.pack(fill='x')
        panel.button(row, '添加图片 / 文件…', self.add).pack(side='left')
        panel.button(row, '粘贴剪贴板图片', self.paste).pack(side='left', padx=4)
        panel.button(row, '清空附件', self.clear).pack(side='left')
        panel.button(row, '打开记录目录', lambda: os.startfile(self.link.history)).pack(side='right')
        self.attachment_text = tk.StringVar(value='未添加附件')
        ttk.Label(composer, textvariable=self.attachment_text, wraplength=950).pack(anchor='w')
        self.previews = ttk.Frame(composer); self.previews.pack(fill='x')
        self.input = tk.Text(composer, height=3, wrap='word', font=('Microsoft YaHei UI', 10))
        self.input.pack(fill='x', pady=4)
        self.input.bind('<Control-Return>', lambda event: self.send())
        self.input.bind('<Control-v>', self.paste_event)
        action = ttk.Frame(composer); action.pack(fill='x')
        panel.button(action, '发送到 OpenCode', self.send).pack(side='left')
        panel.button(action, '刷新当前会话', self.refresh).pack(side='left', padx=4)
        # Keep interrupt available while a worker waits; this is a backend cancel.
        ttk.Button(action, text='中止 OpenCode 本轮', command=self.interrupt).pack(side='right')
        ttk.Label(composer, text='原生建模仍可使用专用页。斜杠命令、终端、差异审阅等完整操作可在同一会话的 OpenCode 界面中继续。', wraplength=950).pack(anchor='w', pady=4)

    def put(self, text):
        position = self.output.yview()
        self.output.configure(state='normal'); self.output.delete('1.0', 'end'); self.output.insert('1.0', text)
        self.output.configure(state='disabled')
        if not position or position[1] > .98: self.output.see('end')

    def task(self, action, done):
        if self.panel.busy: return
        self.panel.controller.cancel.clear(); self.panel.set_busy(True)
        self.editing(False)
        def work():
            try:
                result = action()
                self.panel.events.put(('native_callback', lambda: self.finish(done, result)))
            except Exception as error:
                self.panel.events.put(('native_callback', lambda message=str(error): self.failed(message)))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, done, value):
        self.panel.set_busy(False); self.editing(True); done(value)

    def failed(self, text):
        self.panel.set_busy(False); self.editing(True); self.status.set(text)
        self.panel.append(self.panel.logbox, 'OpenCode：' + text + '\n')
        messagebox.showerror('OpenCode', text, parent=self.root)

    def editing(self, enabled):
        self.input.configure(state='normal' if enabled else 'disabled')
        for choice in (self.sessions, self.models, self.agents, self.variants):
            choice.configure(state='readonly' if enabled else 'disabled')

    def update_variants(self, event=None):
        self.variant.set('沿用模型变体')
        selected = next((m for m in self.catalog['models'] if m['providerID'] + '/' + m['id'] == self.model.get()), None)
        values = selected.get('variants', []) if selected else []
        self.variants['values'] = ['沿用模型变体'] + [x['id'] if isinstance(x, dict) else x for x in values]

    def connect(self):
        def work():
            status = self.link.connect()
            return status, self.link.catalog(), self.link.sessions(), self.link.refresh() if self.link.session else None
        def done(value):
            status, self.catalog, sessions, history = value
            self.update_sessions(sessions)
            self.models['values'] = ['沿用会话 / OpenCode 默认'] + [m['providerID'] + '/' + m['id'] for m in self.catalog['models']]
            self.agents['values'] = ['沿用会话 Agent'] + [a['id'] for a in self.catalog['agents']]
            names = ', '.join(x['name'] + ':' + x['status']['status'] for x in status['mcp']['data'])
            self.status.set('已连接 · ' + names + ' · ' + str(self.link.project))
            if history: self.put(history['text'])
        self.task(work, done)

    def update_sessions(self, rows):
        self.session_map = {x.get('title', '未命名') + ' · ' + x['id']: x['id'] for x in rows}
        self.sessions['values'] = list(self.session_map)
        self.session_value.set(next((label for label,sid in self.session_map.items() if sid == self.link.session), self.link.session or '点击新对话，或直接输入消息'))

    def selected(self):
        model = None
        if self.model.get() != '沿用会话 / OpenCode 默认':
            provider, name = self.model.get().split('/', 1)
            model = {'providerID': provider, 'id': name}
            if self.variant.get() != '沿用模型变体': model['variant'] = self.variant.get()
        agent = self.agent.get() if self.agent.get() != '沿用会话 Agent' else None
        return model, agent

    def new(self):
        model, agent = self.selected()
        def work():
            if self.link.url is None: self.link.connect()
            self.link.new_session(model=model, agent=agent)
            return self.link.sessions()
        self.task(work, lambda rows: (self.update_sessions(rows), self.put('新会话已建立，请输入消息。')))

    def load(self, event=None):
        if self.panel.busy: return
        sid = self.session_map.get(self.session_value.get())
        if not sid: return
        def work():
            self.link.select_session(sid)
            return self.link.refresh()
        def done(result):
            self.model.set('沿用会话 / OpenCode 默认'); self.agent.set('沿用会话 Agent'); self.update_variants()
            self.put(result['text'])
        self.task(work, done)

    def refresh(self):
        if self.link.url is None: return self.connect()
        def done(result):
            self.put(result['text']); self.status.set('本轮仍在进行或等待确认' if result['pending'] else '会话已刷新')
        self.task(self.link.refresh, done)

    def thumbnails(self):
        self.photos = []
        for widget in self.previews.winfo_children(): widget.destroy()
        from io import BytesIO
        for item in self.attachments:
            if not item['mime'].startswith('image/'): continue
            try:
                with Image.open(BytesIO(item['data'])) as picture:
                    picture.thumbnail((100, 65)); photo = ImageTk.PhotoImage(picture.copy())
            except (OSError, ValueError):
                continue
            self.photos.append(photo)
            ttk.Label(self.previews, image=photo).pack(side='left', padx=3)
        self.attachment_text.set('；'.join(x['name'] + ('（已适配图片大小）' if x.get('transform') else '') for x in self.attachments) or '未添加附件')

    def add(self):
        paths = filedialog.askopenfilenames(parent=self.root, title='选择图片或文件', filetypes=[('图片', '*.png *.jpg *.jpeg'), ('所有文件', '*.*')])
        if paths:
            try:
                items = [read_attachment(p) for p in paths]
                self.attachments.extend(items); self.thumbnails()
            except Exception as error: self.failed(str(error))

    def paste_event(self, event):
        try: value = ImageGrab.grabclipboard()
        except Exception: return None
        if isinstance(value, Image.Image):
            self.paste(value); return 'break'
        return None

    def paste(self, picture=None):
        if self.panel.busy: return
        try:
            value = picture if picture is not None else ImageGrab.grabclipboard()
            if isinstance(value, list):
                self.attachments.extend(read_attachment(p) for p in value)
            elif isinstance(value, Image.Image):
                import time
                folder = self.link.history / 'clipboard'; folder.mkdir(exist_ok=True)
                path = folder / ('Clipboard-' + str(time.time_ns()) + '.png')
                value.save(path, 'PNG'); self.attachments.append(read_attachment(path))
            else:
                self.status.set('剪贴板中没有图片'); return
            self.thumbnails()
        except Exception as error: self.failed(str(error))

    def clear(self):
        self.attachments = []; self.thumbnails()

    def send(self):
        if self.panel.busy: return
        text = self.input.get('1.0', 'end').strip()
        images = tuple(self.attachments)
        model, agent = self.selected()
        if not text and not images: return
        self.status.set('OpenCode 正在处理…')
        def work():
            if self.link.url is None: self.link.connect()
            if not self.link.session: self.link.new_session(model=model, agent=agent)
            else: self.link.switch(model, agent)
            def update(value):
                self.panel.events.put(('native_callback', lambda: self.put(value)))
            result = self.link.send(text, images, cancel=self.panel.controller.cancel, progress=update)
            return result, self.link.sessions()
        def done(value):
            result, rows = value
            self.put(result['text']); self.update_sessions(rows)
            self.input.delete('1.0', 'end'); self.clear()
            self.status.set('本轮 ' + str(result['outcome']) + ' · 会话 ' + self.link.session)
        self.task(work, done)

    def interrupt(self):
        if not self.link.session or self.link.url is None: return
        def work():
            try:
                self.link.interrupt()
                self.panel.events.put(('native_callback', lambda: self.status.set('已向OpenCode发送中止；CATIA已派发调用仍需核对结果')))
            except Exception as error:
                self.panel.events.put(('native_callback', lambda text=str(error): self.status.set(text)))
        threading.Thread(target=work, daemon=True).start()

    def full(self):
        if self.link.session:
            try: self.link.open_full_interface()
            except Exception as error: self.status.set(str(error))
            return
        if self.panel.busy:
            self.status.set('正在建立会话，请稍后打开完整界面'); return
        model, agent = self.selected()
        def work():
            if self.link.url is None: self.link.connect()
            self.link.new_session(model=model, agent=agent)
            return self.link.sessions()
        self.task(work, lambda rows: (self.update_sessions(rows), self.link.open_full_interface()))

    def project(self):
        if self.panel.busy: return
        path = filedialog.askdirectory(parent=self.root, initialdir=self.link.project, title='选择与OpenCode共用的项目目录')
        if path:
            self.link = OpenCodeLink(self.panel.controller.workspace, path)
            self.put(''); self.connect()
