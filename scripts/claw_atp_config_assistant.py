#!/usr/bin/env python3
"""Tkinter GUI to configure Claw and ATP Telegram credentials step-by-step."""

import tkinter as tk
from tkinter import messagebox, filedialog
from pathlib import Path


FIELDS = [
    {
        "key": "TELEGRAM_CLAW_BOT_TOKEN",
        "label": "Claw bot token",
        "help": "Paste the Telegram token for @Claw_cruz_bot.",
        "multiline": True,
        "secret": False,
    },
    {
        "key": "TELEGRAM_CLAW_CHAT_ID",
        "label": "Claw chat ID",
        "help": "Paste the Telegram chat ID where Claw task messages should go.",
        "multiline": False,
        "secret": False,
    },
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "ATP bot token",
        "help": "Paste the Telegram token used by ATP Control.",
        "multiline": True,
        "secret": False,
    },
    {
        "key": "TELEGRAM_CHAT_ID",
        "label": "ATP chat ID",
        "help": "Paste the Telegram chat ID used by ATP Control.",
        "multiline": False,
        "secret": False,
    },
]


class StepByStepEnvApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Claw / ATP Config Assistant")
        self.root.geometry("760x520")
        self.root.minsize(680, 460)

        self.current_index = 0
        self.values = {}

        self.title_var = tk.StringVar()
        self.help_var = tk.StringVar()
        self.progress_var = tk.StringVar()

        self._build_ui()
        self._load_step()

    def _build_ui(self):
        container = tk.Frame(self.root, padx=18, pady=18)
        container.pack(fill="both", expand=True)

        header = tk.Label(
            container,
            text="Configuration Assistant",
            font=("Arial", 18, "bold"),
            anchor="w",
        )
        header.pack(fill="x", pady=(0, 8))

        progress = tk.Label(
            container,
            textvariable=self.progress_var,
            font=("Arial", 10),
            fg="#555555",
            anchor="w",
        )
        progress.pack(fill="x", pady=(0, 12))

        title = tk.Label(
            container,
            textvariable=self.title_var,
            font=("Arial", 14, "bold"),
            anchor="w",
            justify="left",
        )
        title.pack(fill="x", pady=(0, 8))

        help_label = tk.Label(
            container,
            textvariable=self.help_var,
            font=("Arial", 11),
            fg="#333333",
            wraplength=700,
            justify="left",
            anchor="w",
        )
        help_label.pack(fill="x", pady=(0, 12))

        self.input_frame = tk.Frame(container)
        self.input_frame.pack(fill="both", expand=True)

        self.entry = tk.Entry(self.input_frame, font=("Arial", 12))
        self.text = tk.Text(self.input_frame, wrap="word", font=("Arial", 12), height=12)

        button_row = tk.Frame(container)
        button_row.pack(fill="x", pady=(12, 0))

        self.back_btn = tk.Button(button_row, text="Back", width=12, command=self._go_back)
        self.back_btn.pack(side="left")

        paste_btn = tk.Button(button_row, text="Paste from clipboard", width=18, command=self._paste_clipboard)
        paste_btn.pack(side="left", padx=(8, 0))

        clear_btn = tk.Button(button_row, text="Clear", width=12, command=self._clear_input)
        clear_btn.pack(side="left", padx=(8, 0))

        self.next_btn = tk.Button(button_row, text="Next", width=12, command=self._go_next)
        self.next_btn.pack(side="right")

        save_btn = tk.Button(button_row, text="Save .env", width=12, command=self._save_file)
        save_btn.pack(side="right", padx=(0, 8))

    def _current_field(self):
        return FIELDS[self.current_index]

    def _load_step(self):
        field = self._current_field()
        total = len(FIELDS)
        self.progress_var.set(f"Step {self.current_index + 1} of {total}")
        self.title_var.set(f"{field['label']}  ({field['key']})")
        self.help_var.set(field["help"])

        for widget in self.input_frame.winfo_children():
            widget.pack_forget()

        saved_value = self.values.get(field["key"], "")

        if field["multiline"]:
            self.text.pack(fill="both", expand=True)
            self.text.delete("1.0", "end")
            self.text.insert("1.0", saved_value)
        else:
            self.entry.config(show="*" if field["secret"] else "")
            self.entry.pack(fill="x", pady=(0, 8))
            self.entry.delete(0, "end")
            self.entry.insert(0, saved_value)

        self.back_btn.config(state="normal" if self.current_index > 0 else "disabled")
        self.next_btn.config(text="Finish" if self.current_index == len(FIELDS) - 1 else "Next")

    def _get_input_value(self):
        field = self._current_field()
        if field["multiline"]:
            return self.text.get("1.0", "end").strip()
        return self.entry.get().strip()

    def _go_back(self):
        self.values[self._current_field()["key"]] = self._get_input_value()
        self.current_index -= 1
        self._load_step()

    def _go_next(self):
        if not self._get_input_value():
            messagebox.showwarning("Empty", "Please enter a value before continuing.")
            return
        self.values[self._current_field()["key"]] = self._get_input_value()
        if self.current_index < len(FIELDS) - 1:
            self.current_index += 1
            self._load_step()
        else:
            messagebox.showinfo("Done", "All done. Use 'Save .env' to write to file.")

    def _paste_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard", "Could not read clipboard.")
            return
        field = self._current_field()
        if field["multiline"]:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
        else:
            self.entry.delete(0, "end")
            self.entry.insert(0, text)

    def _clear_input(self):
        field = self._current_field()
        if field["multiline"]:
            self.text.delete("1.0", "end")
        else:
            self.entry.delete(0, "end")

    def _save_file(self):
        for field in FIELDS:
            if field["key"] not in self.values:
                self.values[field["key"]] = ""
        path = filedialog.asksaveasfilename(
            title="Save .env",
            defaultextension=".env",
            filetypes=[("Env files", "*.env"), ("All files", "*.*")],
            initialdir=str(Path.cwd()),
            initialfile=".env",
        )
        if not path:
            return
        lines = []
        for field in FIELDS:
            val = self.values.get(field["key"], "")
            if val:
                lines.append(f"{field['key']}={val}")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        messagebox.showinfo("Saved", f"Saved to {path}")


def main():
    root = tk.Tk()
    app = StepByStepEnvApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
