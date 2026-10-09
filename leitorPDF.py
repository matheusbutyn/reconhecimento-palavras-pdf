import os
import unicodedata
import tkinter
import customtkinter
from tkinter import filedialog

# O PyPDF2 foi descontinuado e continua como "pypdf"; usa o novo se estiver instalado
try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader

customtkinter.set_appearance_mode("system")
customtkinter.set_default_color_theme("blue")

COR_BLOCO = ("#d9d9d9", "#3a3a3a")       # Bloco normal (modo claro, modo escuro)
COR_DESTAQUE = ("#3b8ed0", "#1f6aa5")    # Bloco que corresponde à busca
PAD = 6                                  # Espaço entre os blocos
MAX_RESULTADOS = 200                     # Evita travar a interface com buscas muito genéricas


def normalizar(texto):
    """Minúsculas, sem acentos e com espaços simples (JOSÉ  da Silva -> jose da silva)."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


def palavra_corresponde(palavra, termos):
    """Destaca o bloco se ele for igual a um termo ou contiver um termo de 3+ letras.
    (evita que termos curtos como "da" destaquem "DANIEL")"""
    p = normalizar(palavra).strip(".,;:()[]-")
    return any(p == t or (len(t) >= 3 and t in p) for t in termos)


class LinhaEmBlocos(customtkinter.CTkFrame):
    """Mostra uma linha da tabela com cada palavra (separada por espaço) em um bloco."""

    def __init__(self, master, linha, pagina, termos, app):
        super().__init__(master, corner_radius=10)
        self.app = app
        self._ultima_largura = None

        # Cabeçalho: página + botão para copiar a linha inteira
        topo = customtkinter.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=10, pady=(6, 0))

        customtkinter.CTkLabel(
            topo, text=f"Página {pagina}", font=customtkinter.CTkFont(size=11, weight="bold")
        ).pack(side="left")

        customtkinter.CTkButton(
            topo, text="Copiar linha", width=90, height=22,
            font=customtkinter.CTkFont(size=11),
            command=lambda: self.app.copiar(linha),
        ).pack(side="right")

        # Área onde os blocos são posicionados (com quebra automática)
        self.area = customtkinter.CTkFrame(self, fg_color="transparent", height=40)
        self.area.pack(fill="x", padx=4, pady=(0, 6))

        self.blocos = []
        for palavra in linha.split():
            destaque = palavra_corresponde(palavra, termos)
            bloco = customtkinter.CTkLabel(
                self.area,
                text=palavra,
                fg_color=COR_DESTAQUE if destaque else COR_BLOCO,
                text_color=("white" if destaque else ("black", "white")),
                corner_radius=6,
                padx=8,
                cursor="hand2",
            )
            # Clique em um bloco copia o texto dele
            bloco.bind("<Button-1>", lambda e, p=palavra: self.app.copiar(p))
            self.blocos.append(bloco)

        self.area.bind("<Configure>", self._reorganizar)

    def _reorganizar(self, event=None):
        """Distribui os blocos em linhas, quebrando quando não cabem na largura."""
        largura = self.area.winfo_width()
        # Só reorganiza quando a largura muda (mudar a altura também dispara <Configure>)
        if largura <= 1 or largura == self._ultima_largura:
            return
        self._ultima_largura = largura

        x = y = PAD
        altura_linha = 0
        for bloco in self.blocos:
            w, h = bloco.winfo_reqwidth(), bloco.winfo_reqheight()
            if x + w > largura and x > PAD:
                x = PAD
                y += altura_linha + PAD
                altura_linha = 0
            # place "puro" do tkinter (em pixels reais, sem o scaling do customtkinter)
            tkinter.Widget.place(bloco, x=x, y=y)
            x += w + PAD
            altura_linha = max(altura_linha, h)

        escala = customtkinter.ScalingTracker.get_widget_scaling(self.area)
        self.area.configure(height=(y + altura_linha + PAD) / escala)


class LeitorPDF(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.title("Leitor de PDF")
        self.geometry("900x650")
        self.minsize(600, 400)

        self.linhas = []        # Lista de (página, linha original, linha normalizada)
        self._texto_status = "Resultados:"
        self._timer_status = None

        # --- Seleção do arquivo ---
        frame_arquivo = customtkinter.CTkFrame(self)
        frame_arquivo.pack(fill="x", padx=10, pady=(10, 5))

        self.btn_abrir = customtkinter.CTkButton(
            frame_arquivo, text="Selecionar PDF", command=self.abrir_pdf
        )
        self.btn_abrir.pack(side="left", padx=10, pady=10)

        self.lbl_arquivo = customtkinter.CTkLabel(frame_arquivo, text="Nenhum arquivo selecionado")
        self.lbl_arquivo.pack(side="left", padx=10)

        # --- Nome a ser procurado ---
        frame_busca = customtkinter.CTkFrame(self)
        frame_busca.pack(fill="x", padx=10, pady=5)

        self.entry_busca = customtkinter.CTkEntry(
            frame_busca, placeholder_text="Digite o nome a ser procurado (ex: NOME NOME-DO-MEIO SOBRENOME)"
        )
        self.entry_busca.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        self.entry_busca.bind("<Return>", lambda e: self.buscar())
        self.entry_busca.bind("<Escape>", lambda e: self.entry_busca.delete(0, "end"))

        customtkinter.CTkButton(
            frame_busca, text="Buscar", width=100, command=self.buscar
        ).pack(side="left", padx=10)

        # --- Modo de busca ---
        frame_modo = customtkinter.CTkFrame(self)
        frame_modo.pack(fill="x", padx=10, pady=5)

        self.modo = customtkinter.StringVar(value="frase")
        for texto, valor in [("Nome completo", "frase"),
                             ("Qualquer palavra", "qualquer"),
                             ("Todas as palavras", "todas")]:
            customtkinter.CTkRadioButton(
                frame_modo, text=texto, variable=self.modo, value=valor,
                command=lambda: self.buscar(silencioso=True),  # refaz a busca ao trocar o modo
            ).pack(side="left", padx=10, pady=10)

        # --- Resultados ---
        self.lbl_resultado = customtkinter.CTkLabel(self, text=self._texto_status)
        self.lbl_resultado.pack(anchor="w", padx=20)

        self.frame_resultados = customtkinter.CTkScrollableFrame(self)
        self.frame_resultados.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Atalho: Ctrl+O abre um PDF
        self.bind("<Control-o>", lambda e: self.abrir_pdf())

        self.mensagem("Clique em \"Selecionar PDF\" (ou Ctrl+O) para começar.")

    # ------------------------------------------------------------------ PDF
    def abrir_pdf(self):
        # Open a file dialog to select a PDF file
        pdf_path = filedialog.askopenfilename(
            title="Selecione um arquivo PDF",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")]
        )
        if not pdf_path:
            return

        nome_arquivo = os.path.basename(pdf_path)
        self.mensagem(f"Carregando {nome_arquivo}...")
        self.btn_abrir.configure(state="disabled")
        self.update()  # mostra a mensagem antes de começar a leitura

        try:
            # Open the PDF file and extract text from all pages
            with open(pdf_path, "rb") as pdf_file:
                pdf_reader = PdfReader(pdf_file)
                if pdf_reader.is_encrypted:
                    pdf_reader.decrypt("")  # muitos PDFs "protegidos" abrem com senha vazia

                linhas = []
                for num, page in enumerate(pdf_reader.pages, start=1):
                    for linha in (page.extract_text() or "").split("\n"):
                        linha = " ".join(linha.split())  # remove espaços repetidos
                        if linha:
                            linhas.append((num, linha, normalizar(linha)))
                total_paginas = len(pdf_reader.pages)
        except Exception as erro:
            self.mensagem(f"Não foi possível ler o PDF:\n{erro}")
            return
        finally:
            self.btn_abrir.configure(state="normal")

        self.linhas = linhas
        self.lbl_arquivo.configure(text=nome_arquivo)
        self.definir_status("Resultados:")

        if not linhas:
            self.mensagem("Nenhum texto encontrado no PDF.\n"
                          "Ele pode ser uma imagem escaneada (precisaria de OCR).")
            return

        self.mensagem(f"PDF carregado ({total_paginas} página(s), {len(linhas)} linhas).\n"
                      "Digite o nome e clique em Buscar.")
        self.entry_busca.focus_set()

    # ---------------------------------------------------------------- Busca
    def buscar(self, silencioso=False):
        if not self.linhas:
            if not silencioso:
                self.mensagem("Selecione um PDF primeiro.")
            return

        busca = normalizar(self.entry_busca.get())
        if not busca:
            if not silencioso:
                self.mensagem("Digite algum nome para procurar.")
            return

        # Os nomes são separados por espaço
        termos = busca.split()
        modo = self.modo.get()

        # Search (sem diferenciar maiúsculas nem acentos)
        encontradas = []
        for pagina, linha, l in self.linhas:
            if modo == "frase":
                ok = busca in l
            elif modo == "qualquer":
                ok = any(t in l for t in termos)
            else:  # todas
                ok = all(t in l for t in termos)
            if ok:
                encontradas.append((pagina, linha))

        self.limpar_resultados()
        if not encontradas:
            self.definir_status("Resultados: 0 linhas")
            self.mensagem(f'Nenhuma linha contém "{self.entry_busca.get().strip()}".')
            return

        status = f"Resultados: {len(encontradas)} linha(s)"
        if len(encontradas) > MAX_RESULTADOS:
            status += f" — mostrando as {MAX_RESULTADOS} primeiras, refine a busca"
        self.definir_status(status + "   (clique em um bloco para copiar)")

        for pagina, linha in encontradas[:MAX_RESULTADOS]:
            LinhaEmBlocos(self.frame_resultados, linha, pagina, termos, self).pack(
                fill="x", padx=5, pady=5
            )

        # Volta a rolagem para o topo a cada nova busca
        self.frame_resultados._parent_canvas.yview_moveto(0)

    # ------------------------------------------------------------ Auxiliares
    def limpar_resultados(self):
        for w in self.frame_resultados.winfo_children():
            w.destroy()

    def mensagem(self, texto):
        self.limpar_resultados()
        customtkinter.CTkLabel(self.frame_resultados, text=texto, justify="center").pack(pady=20)

    def definir_status(self, texto):
        self._texto_status = texto
        self.lbl_resultado.configure(text=texto)

    def copiar(self, texto):
        self.clipboard_clear()
        self.clipboard_append(texto)
        self.lbl_resultado.configure(text=f'Copiado: "{texto}"')

        # Depois de 2 s volta a mostrar a contagem de resultados
        if self._timer_status:
            self.after_cancel(self._timer_status)
        self._timer_status = self.after(
            2000, lambda: self.lbl_resultado.configure(text=self._texto_status)
        )


if __name__ == "__main__":
    app = LeitorPDF()
    app.mainloop()