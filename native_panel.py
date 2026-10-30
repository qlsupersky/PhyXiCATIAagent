"""Primary plugin page for natural-language native modeling."""
import json
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from native_contract import validate_checks
from native_workflow import NativeWorkflow, proposal_hash
from native_images import from_path, manifest as image_manifest, input_hash
from native_examples import EXAMPLES


class NativePage:
    def __init__(self, panel, parent, config):
        self.panel, self.root = panel, panel.root
        self.record = None
        self.manifest = None
        self.images = []
        self.workflow = NativeWorkflow(panel.controller.workspace, config.get('native_gate_path'),
                         lambda msg: panel.events.put(('log', msg)))
        ttk.Label(parent, text='自然语言原生建模 · OpenCode + MCP', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(parent, text='描述零件 → 自动生成专属CATScript → 自动执行MCP → 保存、重开核验。免审核模式已启用。', wraplength=950).pack(anchor='w', pady=6)
        row = ttk.Frame(parent); row.pack(fill='x')
        panel.button(row, '连接 / 检查引擎', self.connect).pack(side='left')
        ttk.Label(row, text='当前模型：DeepSeek Flash · 官方连接（沿用本机加密凭据）').pack(side='left', padx=12)
        self.state = tk.StringVar(value='尚未连接；输入需求后生成方案')
        ttk.Label(parent, textvariable=self.state, wraplength=950).pack(anchor='w', pady=5)
        self.requirement = tk.Text(parent, height=4, font=('Microsoft YaHei UI', 10), wrap='word')
        self.requirement.pack(fill='x')
        self.requirement.insert('1.0', '创建一块100×60×12mm的矩形安装板，在XY原点中心开直径20mm的通孔。矩形以原点为中心，向正Z拉伸；保留原生草图、拉伸和切除特征。')
        examples = ttk.Frame(parent); examples.pack(fill='x', pady=4)
        ttk.Label(examples, text='可编辑的需求示例：').pack(side='left')
        self.example = tk.StringVar(value='自由需求')
        ttk.Combobox(examples, textvariable=self.example, values=list(EXAMPLES), state='readonly', width=26).pack(side='left')
        panel.button(examples, '填入示例需求', self.use_example).pack(side='left', padx=5)
        panel.button(examples, '添加参考图…', self.add_images).pack(side='left')
        panel.button(examples, '清空参考图', self.clear_images).pack(side='left', padx=5)
        self.image_status = tk.StringVar(value='未附图：仅按文字建模')
        ttk.Label(parent, textvariable=self.image_status, wraplength=950).pack(anchor='w')
        actions = ttk.Frame(parent); actions.pack(fill='x', pady=6)
        panel.button(actions, '生成并自动执行', self.run_automatic).pack(side='left')
        panel.button(actions, '仅生成宏', self.generate).pack(side='left', padx=6)
        panel.button(actions, '执行已生成宏', self.review).pack(side='left', padx=6)
        panel.button(actions, '刷新任务结果', self.refresh).pack(side='left')
        panel.button(actions, '打开任务记录…', self.load).pack(side='left', padx=6)
        panel.button(actions, '打开本次目录', self.open_folder).pack(side='left')
        panel.button(actions, '图片辅助核对', self.compare).pack(side='left', padx=6)
        self.views = ttk.Notebook(parent); self.views.pack(fill='both', expand=True)
        self.summary = self.text_tab('方案 / 执行结果', readonly=True)
        self.source = self.text_tab('完整原生宏', readonly=True, font=('Consolas', 10))
        self.checks = self.text_tab('检查项（可校正）', readonly=False, font=('Consolas', 10))
        self.visual = self.text_tab('图片辅助核对', readonly=True)
        ttk.Label(parent, text='本入口新建独立原生零件；修改需求时生成完整新版本。无需批准弹窗；检查项来自模型，回读不等于完整设计验收。', wraplength=950).pack(anchor='w', pady=5)
        ttk.Label(parent, text='中止只停止等待，已派发的CATIA操作可能继续；结果未知会阻塞后续派发。历史方案不会自动重放。', wraplength=950).pack(anchor='w')

    def text_tab(self, label, readonly, font=('Microsoft YaHei UI', 10)):
        frame = ttk.Frame(self.views); self.views.add(frame, text=label)
        widget = tk.Text(frame, wrap='word', font=font, state='disabled' if readonly else 'normal')
        scroll = ttk.Scrollbar(frame, command=widget.yview); scroll.pack(side='right', fill='y')
        widget.configure(yscrollcommand=scroll.set); widget.pack(fill='both', expand=True)
        return widget

    def put(self, widget, text, readonly=True):
        widget.configure(state='normal'); widget.delete('1.0', 'end'); widget.insert('1.0', text)
        if readonly: widget.configure(state='disabled')

    def task(self, action, done):
        if self.panel.busy:
            return
        self.panel.controller.cancel.clear(); self.panel.set_busy(True)
        def work():
            try:
                value = action()
                self.panel.events.put(('native_callback', lambda: done(value)))
            except Exception as error:
                self.panel.events.put(('native_callback', lambda message=str(error): self.failed(message)))
        threading.Thread(target=work, daemon=True).start()

    def failed(self, message):
        self.state.set(message); self.panel.set_busy(False)
        self.panel.append(self.panel.logbox, '原生建模：' + message + '\n')
        messagebox.showerror('原生建模未完成', message, parent=self.root)

    def connect(self):
        def done(value):
            self.state.set('引擎已连接；模型 ' + value['model'] + '；执行门 ' + value['gate']['status'])
            self.panel.set_busy(False)
        self.task(self.workflow.connect, done)

    def editable(self):
        if self.panel.busy:
            return False
        if self.manifest and self.workflow.service.job(self.manifest['job_id'])['state'] in ('RUNNING', 'FROZEN'):
            messagebox.showinfo('先核对当前任务', '当前任务仍在运行或冻结，先核对结果。', parent=self.root)
            return False
        return True

    def update_images(self, images):
        info = image_manifest(images)
        self.images = list(images)
        self.record = None; self.manifest = None
        self.put(self.source, ''); self.put(self.checks, '', False)
        self.put(self.summary, '输入已变化，请重新生成方案。')
        self.put(self.visual, '')
        label = '；'.join(x['filename'] for x in info)
        self.image_status.set(('将发送至当前模型：' + label + '（' + str(len(info)) + '张图片快照）') if info else '未附图：仅按文字建模')
        if any(x.get('transform') for x in info):
            self.image_status.set(self.image_status.get() + '；大图已缩放，原图哈希及转换在清单中保留')
        self.state.set('输入已变化；请重新生成')

    def use_example(self):
        if not self.editable(): return
        text = EXAMPLES[self.example.get()]
        if not text: return
        self.update_images(self.images)
        self.requirement.delete('1.0', 'end'); self.requirement.insert('1.0', text)

    def add_images(self):
        if not self.editable(): return
        paths = filedialog.askopenfilenames(parent=self.root, title='选择参考图（会发送至当前模型）',
                    filetypes=[('PNG/JPEG参考图', '*.png *.jpg *.jpeg')])
        if not paths: return
        try:
            self.update_images(self.images + [from_path(p) for p in paths])
        except Exception as error:
            messagebox.showerror('参考图未添加', str(error), parent=self.root)

    def clear_images(self):
        if self.editable(): self.update_images([])

    def current_input_hash(self):
        return input_hash(self.requirement.get('1.0', 'end').strip(), image_manifest(self.images))

    def generate(self):
        requirement = self.requirement.get('1.0', 'end').strip()
        images = tuple(self.images)
        if self.manifest:
            row = self.workflow.service.job(self.manifest['job_id'])
            if row['state'] in ('RUNNING', 'FROZEN'):
                self.failed('当前任务仍在运行或冻结；先核对任务结果，不生成新的执行任务。'); return
        # Any new requirement invalidates the old displayed approval candidate.
        self.record = None; self.manifest = None
        self.put(self.source, ''); self.put(self.checks, '', False)
        self.state.set('OpenCode正在根据需求编写方案和原生宏…')
        def done(record):
            self.record = record
            self.put(self.summary, record['proposal']['summary'])
            self.put(self.source, record['proposal']['macro_ascii'])
            self.put(self.checks, json.dumps(record['proposal']['checks'], ensure_ascii=False, indent=2), False)
            self.state.set('宏已生成；尚未操作CATIA。可直接执行，无需审核。')
            self.panel.set_busy(False)
        self.task(lambda: self.workflow.generate(requirement, self.panel.controller.cancel, images=images), done)

    def run_automatic(self):
        if not self.editable(): return
        requirement = self.requirement.get('1.0', 'end').strip()
        images = tuple(self.images)
        self.record = None; self.manifest = None
        self.put(self.source, ''); self.put(self.checks, '', False)
        self.state.set('正在生成原生宏，随后将自动执行…')
        def prepared(record, manifest):
            def show():
                self.record = record; self.manifest = manifest
                self.put(self.source, record['proposal']['macro_ascii'])
                self.put(self.checks, json.dumps(record['proposal']['checks'], ensure_ascii=False, indent=2), False)
                self.state.set('宏已生成，正在自动执行MCP并核验结果…')
            self.panel.events.put(('native_callback', show))
        self.task(lambda: self.workflow.generate_and_execute(requirement, self.panel.controller.cancel,
                  images=images, on_prepared=prepared), self.completed)

    def review(self):
        if self.panel.busy: return
        if self.manifest:
            manifest = self.manifest
            origin = json.loads((self.workflow.service.folder(manifest['job_id']) / 'proposal-origin.json').read_text(encoding='utf-8'))
            if (self.requirement.get('1.0', 'end').strip() != manifest['requirement'] or
                    (origin.get('input_sha256') and self.current_input_hash() != origin['input_sha256'])):
                messagebox.showinfo('需求已变化', '请重新生成新方案。', parent=self.root); return
            self.task(lambda: self.workflow.execute(manifest, self.panel.controller.cancel), self.completed)
            return
        if not self.record:
            messagebox.showinfo('先生成方案', '请输入需求并点击“生成 / 更新方案”。', parent=self.root); return
        if (self.requirement.get('1.0', 'end').strip() != self.record['requirement'] or
                (self.record.get('input_sha256') and self.current_input_hash() != self.record['input_sha256'])):
            messagebox.showinfo('需求已变化', '请先重新生成方案。', parent=self.root); return
        try:
            checks = validate_checks(json.loads(self.checks.get('1.0', 'end')))
        except Exception as error:
            messagebox.showerror('检查项错误', str(error), parent=self.root); return
        record = json.loads(json.dumps(self.record)); expected = proposal_hash(record['proposal'])
        def run():
            manifest = self.workflow.prepare(record, checks, expected)
            self.panel.events.put(('native_callback', lambda: setattr(self, 'manifest', manifest)))
            return self.workflow.execute(manifest, self.panel.controller.cancel)
        self.task(run, self.completed)

    def completed(self, result):
        self.state.set(('几何未达标；入口已自动释放，可直接提交修正需求。' if result['state']=='FAILED' else '完成：' + result['state']) + '；真实模型MCP调用 ' + str(result['model_MCP_audit']['model_MCP_call_verified']))
        self.put(self.summary, json.dumps(result, ensure_ascii=False, indent=2))
        self.views.select(0); self.panel.set_busy(False)

    def compare(self):
        if not self.manifest:
            messagebox.showinfo('先完成建模', '请先执行方案或打开已成功的任务记录。', parent=self.root); return
        def done(answer):
            self.put(self.visual, answer['text'] + '\n\n原始对话：' + answer['folder'] +
                     ('\n参考图超过3张，本次只比较前3张。' if answer['references_omitted'] else '') +
                     ('\n结果截图已缩放适配模型图片接口；原始截图保留。' if answer['result_image_transform'].get('transform') else ''))
            self.views.select(3)
            self.state.set('图片辅助答复已保存；没有新CATIA调用。精确几何仍以回读为准。')
            self.panel.set_busy(False)
        self.task(lambda: self.workflow.compare(self.manifest['job_id'], self.panel.controller.cancel), done)

    def refresh(self):
        if not self.manifest:
            messagebox.showinfo('没有任务', '请先执行方案，或打开历史任务记录。', parent=self.root); return
        job = self.manifest['job_id']
        def action():
            self.workflow.runtime.connect()
            return self.workflow.refresh(job)
        def done(result):
            self.put(self.summary, json.dumps(result, ensure_ascii=False, indent=2))
            self.state.set('任务 ' + result['state'] + '；执行门 ' + result['gate']['status'] + '；刷新不会重放操作')
            self.panel.set_busy(False)
        self.task(action, done)

    def load(self):
        path = filedialog.askopenfilename(initialdir=self.workflow.service.jobs, filetypes=[('建模任务记录', 'approval.json')])
        if not path: return
        try:
            manifest = json.loads(Path(path).read_text(encoding='utf-8'))
            folder = self.workflow.service.folder(manifest['job_id'])
            if Path(path).resolve() != (folder / 'approval.json').resolve():
                raise ValueError('只能打开当前工作目录中的任务记录')
            row = self.workflow.service.job(manifest['job_id'])
            # DB is authoritative; a caller-supplied manifest cannot change dispatch.
            manifest = json.loads(row['manifest_json'])
            self.images = self.workflow.references_for_job(manifest['job_id'])
            self.image_status.set('历史参考图快照：' + '；'.join(im.filename for im in self.images) if self.images else '历史任务未附图')
            self.manifest = manifest; self.record = None
            self.requirement.delete('1.0', 'end'); self.requirement.insert('1.0', manifest['requirement'])
            self.put(self.source, (folder / 'REVIEWED.CATScript').read_bytes().decode('ascii'))
            self.put(self.checks, (folder / 'CHECKS.json').read_text(), False)
            self.refresh()
        except Exception as error:
            self.failed(str(error))

    def open_folder(self):
        path = self.workflow.service.folder(self.manifest['job_id']) if self.manifest else self.workflow.history
        os.startfile(path)
