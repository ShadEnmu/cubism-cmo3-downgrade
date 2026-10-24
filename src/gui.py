"""Window for the 5.4 alpha -> 5.3 converter."""
import os, threading, traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cmo3conv import convert, default_output, ConvertError, __version__


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Cubism 5.4 alpha → 5.3 конвертер v{__version__}')
        self.geometry('640x380')
        self.minsize(520, 320)
        self.src = tk.StringVar(); self.dst = tk.StringVar()

        f = ttk.Frame(self, padding=12); f.pack(fill='both', expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text='Модель 5.4 (.cmo3):').grid(row=0, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.src).grid(row=0, column=1, sticky='ew', padx=6)
        ttk.Button(f, text='Выбрать…', command=self.pick_src).grid(row=0, column=2)
        ttk.Label(f, text='Сохранить как:').grid(row=1, column=0, sticky='w', pady=(8, 0))
        ttk.Entry(f, textvariable=self.dst).grid(row=1, column=1, sticky='ew', padx=6, pady=(8, 0))
        ttk.Button(f, text='Изменить…', command=self.pick_dst).grid(row=1, column=2, pady=(8, 0))

        self.btn = ttk.Button(f, text='Конвертировать', command=self.start)
        self.btn.grid(row=2, column=0, columnspan=3, pady=12, sticky='ew')
        self.bar = ttk.Progressbar(f, mode='indeterminate')
        self.bar.grid(row=3, column=0, columnspan=3, sticky='ew')

        self.log = tk.Text(f, height=10, state='disabled', wrap='word')
        self.log.grid(row=4, column=0, columnspan=3, sticky='nsew', pady=(8, 0))
        f.rowconfigure(4, weight=1)
        self.write('Выберите файл .cmo3, сохранённый в Cubism 5.4 alpha.\n'
                   'Исходный файл не изменяется — результат сохраняется отдельно.')

    def write(self, msg):
        self.log.configure(state='normal'); self.log.insert('end', msg + '\n')
        self.log.see('end'); self.log.configure(state='disabled')

    def pick_src(self):
        p = filedialog.askopenfilename(title='Модель Cubism 5.4', filetypes=[('Cubism model', '*.cmo3'), ('Все файлы', '*.*')])
        if p:
            self.src.set(p); self.dst.set(default_output(p))

    def pick_dst(self):
        init = self.dst.get() or default_output(self.src.get() or 'model.cmo3')
        p = filedialog.asksaveasfilename(title='Сохранить для 5.3', defaultextension='.cmo3',
                                         initialdir=os.path.dirname(init), initialfile=os.path.basename(init),
                                         filetypes=[('Cubism model', '*.cmo3')])
        if p: self.dst.set(p)

    def start(self):
        src, dst = self.src.get().strip(), self.dst.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showwarning('Нет файла', 'Выберите исходный файл .cmo3.'); return
        if not dst:
            dst = default_output(src); self.dst.set(dst)
        if os.path.abspath(src) == os.path.abspath(dst):
            messagebox.showwarning('Тот же файл', 'Сохраните результат под другим именем, чтобы не затереть оригинал.'); return
        if os.path.exists(dst) and not messagebox.askyesno('Файл существует', f'{dst}\n\nЗаменить?'):
            return
        self.btn.configure(state='disabled'); self.bar.start(12)
        self.write(f'\nКонвертация: {src}')
        threading.Thread(target=self.run, args=(src, dst), daemon=True).start()

    def run(self, src, dst):
        log = lambda m: self.after(0, self.write, m)
        try:
            convert(src, dst, log)
            self.after(0, self.done, True, f'Готово!\n\n{dst}\n\nОткройте файл в Cubism 5.3 и сохраните его там.')
        except ConvertError as e:
            self.after(0, self.done, False, str(e))
        except Exception:
            self.after(0, self.done, False, 'Непредвиденная ошибка:\n' + traceback.format_exc(limit=3))

    def done(self, ok, msg):
        self.bar.stop(); self.btn.configure(state='normal')
        self.write(msg if ok else 'Ошибка: ' + msg)
        (messagebox.showinfo if ok else messagebox.showerror)('Готово' if ok else 'Ошибка', msg)


if __name__ == '__main__':
    App().mainloop()
