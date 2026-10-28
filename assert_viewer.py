#!/usr/bin/env python3
# Assert Viewer: GUI runner for Java files that use native `assert` statements.
# Requires a JDK (javac + java) and Python 3 with tkinter.
import os
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HELPER = r"""
import javax.swing.*;
import javax.swing.table.DefaultTableModel;
import java.awt.*;
import java.util.*;
import java.util.List;

class AssertViewerRuntime {
    static class Result {
        String method, expression, status, detail;
        int line;
        Result(String m, int l, String e, boolean ok, String d) {
            method=m; line=l; expression=e; status=ok ? "PASSOU" : "FALHOU"; detail=d;
        }
    }
    static final List<Result> results = Collections.synchronizedList(new ArrayList<>());
    static String currentMethod = "(inicialização)";
    static void method(String name) { currentMethod = name; }

    static void check(boolean ok, int line, String expression) {
        results.add(new Result(currentMethod, line, expression, ok, ok ? "" : "Expressão resultou em false"));
    }
    static void error(int line, String expression, Throwable t) {
        results.add(new Result(currentMethod, line, expression, false,
            t.getClass().getSimpleName() + (t.getMessage() == null ? "" : ": " + t.getMessage())));
    }
    static void show() {
        SwingUtilities.invokeLater(() -> {
            String[] cols = {"Resultado", "Método", "Linha original", "Assert", "Detalhes"};
            DefaultTableModel model = new DefaultTableModel(cols, 0) {
                public boolean isCellEditable(int r, int c) { return false; }
            };
            for (Result r : results)
                model.addRow(new Object[]{r.status, r.method, r.line, r.expression, r.detail});
            JTable table = new JTable(model);
            table.setRowHeight(24);
            table.setAutoCreateRowSorter(true);
            table.getColumnModel().getColumn(0).setPreferredWidth(85);
            table.getColumnModel().getColumn(1).setPreferredWidth(170);
            table.getColumnModel().getColumn(2).setPreferredWidth(85);
            table.getColumnModel().getColumn(3).setPreferredWidth(420);
            table.getColumnModel().getColumn(4).setPreferredWidth(260);
            table.setDefaultRenderer(Object.class, new javax.swing.table.DefaultTableCellRenderer() {
                public Component getTableCellRendererComponent(JTable t, Object v, boolean s, boolean f, int row, int col) {
                    Component c = super.getTableCellRendererComponent(t, v, s, f, row, col);
                    String status = String.valueOf(t.getModel().getValueAt(t.convertRowIndexToModel(row), 0));
                    if (!s) c.setForeground(status.equals("PASSOU") ? new Color(0,125,55) : new Color(190,35,35));
                    return c;
                }
            });
            int passed = 0, failed = 0;
            for (Result r : results) if (r.status.equals("PASSOU")) passed++; else failed++;
            JLabel summary = new JLabel("  Total: " + results.size() + "    ✓ " + passed + " passaram    ✗ " + failed + " falharam");
            summary.setBorder(BorderFactory.createEmptyBorder(8,8,8,8));
            JFrame frame = new JFrame("Assert Viewer — resultados");
            frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
            frame.add(summary, BorderLayout.NORTH);
            frame.add(new JScrollPane(table), BorderLayout.CENTER);
            frame.setSize(1100, 600);
            frame.setLocationRelativeTo(null);
            frame.setVisible(true);
        });
    }
}
"""

def split_assert(stmt):
    # stmt is the expression after 'assert' and before its terminating semicolon.
    # Java assert permits: assert condition; or assert condition : detail;
    # Find a top-level colon while ignoring strings/chars and ternary operators.
    depth = 0
    in_str = in_char = esc = False
    ternary = 0
    for i, ch in enumerate(stmt):
        if in_str or in_char:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif in_str and ch == '"': in_str = False
            elif in_char and ch == "'": in_char = False
            continue
        if ch == '"': in_str = True; continue
        if ch == "'": in_char = True; continue
        if ch in "([{": depth += 1
        elif ch in ")]}": depth -= 1
        elif depth == 0:
            if ch == '?': ternary += 1
            elif ch == ':' and ternary:
                ternary -= 1
            elif ch == ':' and ternary == 0:
                return stmt[:i].strip()
    return stmt.strip()

def instrument(source):
    lines = source.splitlines(True)
    out = []
    current_method = None
    brace_depth = 0
    # This lightweight instrumenter targets the usual one-line assert format used in course test files.
    # Multi-line assert expressions are deliberately reported as unsupported.
    for lineno, line in enumerate(lines, 1):
        # Track method names from declarations (test methods and main included).
        m = re.search(r'\b(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\([^;]*\)\s*\{', line)
        if m:
            current_method = m.group(1)
        # Only replace a full assert statement on one line. Preserve indentation and line count.
        match = re.match(r'^(\s*)assert\s+(.+);\s*(?://.*)?(\r?\n)?$', line)
        if match:
            indent, expr, newline = match.groups()
            expr = split_assert(expr)
            # Replace with try/catch so an exception in an assert is reported and later asserts continue.
            expr_java = expr.replace('\\', '\\\\').replace('"', '\\"')
            replacement = (
                f'{indent}try {{ AssertViewerRuntime.check(({expr}), {lineno}, "{expr_java}"); }} '
                f'catch (Throwable __av_e) {{ AssertViewerRuntime.error({lineno}, "{expr_java}", __av_e); }}'
                f'{newline or ""}'
            )
            out.append(replacement)
            continue
        # Mark method context for display; this call is harmless for regular methods.
        if m and current_method:
            out.append(line)
            # Inject a method label immediately after the opening brace on declaration lines.
            # If opening brace is on same line (the expected style), add the label.
            out.append(f'        AssertViewerRuntime.method("{current_method}");\n')
            continue
        out.append(line)
    transformed = ''.join(out)
    # Add GUI display after the main method has finished, before its final closing brace.
    # Identify main method and match its braces while respecting comments/strings approximately.
    mm = re.search(r'\bstatic\s+void\s+main\s*\([^)]*\)\s*\{', transformed)
    if not mm:
        raise ValueError("Não encontrei `public static void main(String[] args)`. O arquivo precisa ter um main que execute os testes.")
    start = transformed.find('{', mm.start())
    depth = 0
    in_str = in_char = line_comment = block_comment = esc = False
    end = None
    for i in range(start, len(transformed)):
        ch = transformed[i]
        nxt = transformed[i+1] if i+1 < len(transformed) else ''
        if line_comment:
            if ch == '\n': line_comment = False
            continue
        if block_comment:
            if ch == '*' and nxt == '/': block_comment = False
            continue
        if in_str or in_char:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif in_str and ch == '"': in_str = False
            elif in_char and ch == "'": in_char = False
            continue
        if ch == '/' and nxt == '/': line_comment = True; continue
        if ch == '/' and nxt == '*': block_comment = True; continue
        if ch == '"': in_str = True; continue
        if ch == "'": in_char = True; continue
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise ValueError("Não consegui localizar o fim do método main.")
    transformed = transformed[:end] + '\n        AssertViewerRuntime.show();\n' + transformed[end:]
    return transformed

class App:
    def __init__(self, root):
        self.root = root
        root.title("Assert Viewer — Java")
        root.geometry("700x230")
        self.path = tk.StringVar()
        ttk.Label(root, text="Arquivo Java de testes (ex.: LinkedListAsserts.java):").pack(anchor="w", padx=14, pady=(14,4))
        row = ttk.Frame(root); row.pack(fill="x", padx=14)
        ttk.Entry(row, textvariable=self.path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Procurar…", command=self.pick).pack(side="left", padx=(8,0))
        self.status = tk.StringVar(value="Selecione o arquivo que contém os asserts e o método main.")
        ttk.Label(root, textvariable=self.status, wraplength=660).pack(anchor="w", padx=14, pady=12)
        self.run_btn = ttk.Button(root, text="Executar e mostrar resultados", command=self.run)
        self.run_btn.pack(anchor="e", padx=14, pady=8)

    def pick(self):
        p = filedialog.askopenfilename(title="Escolha o arquivo de testes", filetypes=[("Java", "*.java"), ("Todos", "*.*")])
        if p: self.path.set(p)

    def run(self):
        path = self.path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Assert Viewer", "Escolha um arquivo .java válido.")
            return
        self.run_btn.configure(state="disabled")
        self.status.set("Executando…")
        threading.Thread(target=self.worker, args=(path,), daemon=True).start()

    def worker(self, path):
        temp = tempfile.mkdtemp(prefix="assert_viewer_")
        try:
            folder = os.path.dirname(os.path.abspath(path))
            # Copy sibling Java sources so dependencies such as LinkedList.java and Node.java are available.
            java_files = [f for f in os.listdir(folder) if f.endswith(".java")]
            for f in java_files:
                shutil.copy2(os.path.join(folder, f), os.path.join(temp, f))
            name = os.path.basename(path)
            original = open(path, encoding="utf-8-sig").read()
            transformed = instrument(original)
            with open(os.path.join(temp, name), "w", encoding="utf-8") as f:
                f.write(transformed)
            with open(os.path.join(temp, "AssertViewerRuntime.java"), "w", encoding="utf-8") as f:
                f.write(HELPER)
            # Compile every source file in the temporary copy. Never edits the professor's files.
            sources = [os.path.join(temp, f) for f in os.listdir(temp) if f.endswith(".java")]
            cp = subprocess.run(["javac", "-encoding", "UTF-8", *sources], cwd=temp, text=True, capture_output=True)
            if cp.returncode:
                raise RuntimeError("Falha na compilação:\n" + cp.stdout + cp.stderr)
            class_name = re.search(r'\bclass\s+([A-Za-z_$][\w$]*)', transformed)
            if not class_name:
                raise RuntimeError("Não encontrei o nome da classe no arquivo.")
            run = subprocess.run(["java", "-ea", "-Djava.awt.headless=false", "-cp", temp, class_name.group(1)], cwd=temp, text=True, capture_output=True, timeout=120)
            if run.returncode:
                # A GUI should still display assertion failures; nonzero means main/runtime failure.
                raise RuntimeError("Erro ao executar:\n" + run.stdout + run.stderr)
            self.root.after(0, lambda: self.status.set("Execução concluída. A janela de resultados deve estar aberta."))
        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda m=msg: messagebox.showerror("Assert Viewer", m))
            self.root.after(0, lambda: self.status.set("A execução não foi concluída."))
        finally:
            # Keep temp files until the child JVM exits; then cleanup.
            shutil.rmtree(temp, ignore_errors=True)
            self.root.after(0, lambda: self.run_btn.configure(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
