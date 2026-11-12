import re
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Disponibilidade da equipe", page_icon="📅", layout="wide")

DIAS = {
    "segunda": "Segunda-feira",
    "terca": "Terça-feira",
    "quarta": "Quarta-feira",
    "quinta": "Quinta-feira",
    "sexta": "Sexta-feira",
}

def normalizar_coluna(nome):
    """Normaliza o nome de uma coluna para facilitar sua identificação."""
    s = str(nome).strip().lower()
    s = (s.replace("á", "a").replace("ã", "a").replace("â", "a")
          .replace("é", "e").replace("ê", "e").replace("í", "i")
          .replace("ó", "o").replace("ô", "o").replace("õ", "o")
          .replace("ú", "u").replace("ç", "c"))
    return re.sub(r"\s+", " ", s)

def separar_areas(valor):
    """
    Converte a resposta da coluna Área em uma lista de áreas.

    Aceita várias áreas separadas por vírgula, ponto e vírgula,
    barra vertical ou quebra de linha. Valores vazios e travessões
    são tratados como ausência de área.
    """
    if pd.isna(valor):
        return []

    texto = str(valor).strip()
    if not texto or texto in {"—", "–", "-", "―"}:
        return []

    partes = re.split(r"[,;\n|]+", texto)
    areas = []
    for parte in partes:
        area = parte.strip()
        if area and area not in {"—", "–", "-", "―"}:
            if area not in areas:
                areas.append(area)
    return areas

def extrair_horarios(resposta):
    """
    Extrai somente intervalos válidos, mesmo quando a resposta também
    contém textos como 'Não tenho disponibilidade'.
    """
    if pd.isna(resposta):
        return []

    horarios = []
    partes = re.split(r"[,;\n]+", str(resposta))

    for parte in partes:
        texto = parte.strip()
        correspondencia = re.fullmatch(
            r"(\d{1,2})\s*h\s*-\s*(\d{1,2})\s*h",
            texto,
            flags=re.IGNORECASE
        )
        if not correspondencia:
            continue

        inicio = int(correspondencia.group(1))
        fim = int(correspondencia.group(2))
        horario = f"{inicio}h-{fim}h"

        if horario not in horarios:
            horarios.append(horario)

    return horarios

def carregar_csv(arquivo):
    dados = arquivo.getvalue()
    # O CSV exportado pelo Google Forms costuma estar em UTF-8.
    try:
        return pd.read_csv(
            io.BytesIO(dados),
            sep=None,
            engine="python",
            encoding="utf-8-sig"
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            io.BytesIO(dados),
            sep=None,
            engine="python",
            encoding="latin-1"
        )

def carregar_google_sheets():
    """Conecta à planilha se as credenciais estiverem configuradas nos Secrets."""
    import gspread
    from google.oauth2.service_account import Credentials

    cfg = st.secrets["google_sheets"]
    credenciais = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    cliente = gspread.authorize(credenciais)
    planilha = cliente.open_by_key(cfg["spreadsheet_id"])
    aba = planilha.worksheet(cfg.get("worksheet", "Respostas ao formulário 1"))
    valores = aba.get_all_values()

    if not valores:
        raise ValueError("A aba da planilha está vazia.")

    return pd.DataFrame(valores[1:], columns=valores[0])

def preparar_dados(df):
    """
    Prepara os dados de participantes e disponibilidades.

    A coluna Área é usada para montar o filtro de áreas. Uma pessoa pode
    estar associada a mais de uma área, caso os valores estejam separados
    por vírgula, ponto e vírgula, barra vertical ou quebra de linha.
    """
    df = df.copy().reset_index(drop=True)
    mapa = {normalizar_coluna(c): c for c in df.columns}

    def achar_coluna(opcoes):
        for opcao in opcoes:
            chave = normalizar_coluna(opcao)
            if chave in mapa:
                return mapa[chave]
        return None

    col_nome = achar_coluna(["Nome"])
    col_categoria = achar_coluna(["Categoria"])
    col_area = achar_coluna(["Área", "Area"])

    if not col_nome or not col_categoria:
        raise ValueError(
            "A planilha precisa conter as colunas 'Nome' e 'Categoria'."
        )

    dias_colunas = {}
    for chave, rotulo in DIAS.items():
        encontrada = None
        for coluna in df.columns:
            if normalizar_coluna(coluna).startswith(chave):
                encontrada = coluna
                break
        if encontrada:
            dias_colunas[rotulo] = encontrada

    if len(dias_colunas) != 5:
        raise ValueError(
            "Não encontrei as cinco colunas de disponibilidade "
            "(segunda a sexta)."
        )

    # Padroniza nomes e remove respostas sem nome.
    df["_nome_limpo"] = df[col_nome].fillna("").astype(str).str.strip()
    df = df[
        (df["_nome_limpo"] != "")
        & (df["_nome_limpo"].str.lower() != "nan")
    ]

    # Se houver mais de uma resposta para a mesma pessoa, considera a última.
    df = df.drop_duplicates(subset=["_nome_limpo"], keep="last")

    pessoas_registros = []
    disponibilidade_registros = []

    for _, linha in df.iterrows():
        nome = linha["_nome_limpo"]
        categoria = (
            str(linha[col_categoria]).strip()
            if pd.notna(linha[col_categoria])
            else ""
        )

        valor_area = linha[col_area] if col_area else ""
        areas = separar_areas(valor_area)

        pessoas_registros.append({
            "Nome": nome,
            "Categoria": categoria,
            "Área": str(valor_area).strip() if pd.notna(valor_area) else "",
            "Áreas": areas,
        })

        for dia, coluna in dias_colunas.items():
            for horario in extrair_horarios(linha[coluna]):
                disponibilidade_registros.append({
                    "Nome": nome,
                    "Categoria": categoria,
                    "Áreas": areas,
                    "Dia": dia,
                    "Horário": horario,
                })

    pessoas = pd.DataFrame(
        pessoas_registros,
        columns=["Nome", "Categoria", "Área", "Áreas"]
    )
    disponibilidades = pd.DataFrame(
        disponibilidade_registros,
        columns=["Nome", "Categoria", "Áreas", "Dia", "Horário"]
    )

    return pessoas, disponibilidades

st.title("📅 Disponibilidade da equipe")
st.caption(
    "Encontre os melhores horários para reuniões de categoria, "
    "capacitações e encontros entre pessoas."
)

with st.sidebar:
    st.header("Fonte dos dados")
    usar_planilha = False

    if "google_sheets" in st.secrets and "gcp_service_account" in st.secrets:
        usar_planilha = st.toggle(
            "Usar planilha Google automaticamente",
            value=True
        )

    if usar_planilha:
        try:
            bruto = carregar_google_sheets()
            st.success("Dados carregados diretamente do Google Sheets.")
        except Exception as erro:
            st.error(f"Não foi possível acessar o Google Sheets: {erro}")
            st.stop()
    else:
        arquivo = st.file_uploader(
            "Envie o CSV de respostas do formulário",
            type=["csv"]
        )

        if arquivo is None:
            st.info("Envie o CSV exportado do Google Forms para começar.")
            st.stop()

        try:
            bruto = carregar_csv(arquivo)
        except Exception as erro:
            st.error(f"Erro ao ler o CSV: {erro}")
            st.stop()

try:
    pessoas, disponibilidades = preparar_dados(bruto)
except Exception as erro:
    st.error(str(erro))
    st.stop()

st.caption(
    f"{len(pessoas)} pessoas carregadas · "
    f"{len(disponibilidades)} combinações de pessoa/horário disponíveis"
)

categorias = sorted({
    valor for valor in pessoas["Categoria"].dropna().astype(str).str.strip()
    if valor and valor.lower() != "nan"
})

areas_disponiveis = sorted({
    area
    for lista_areas in pessoas["Áreas"]
    for area in lista_areas
})

st.subheader("Quem você quer incluir?")
modo = st.radio(
    "Tipo de seleção",
    [
        "Categoria(s)",
        "Área(s)",
        "Pessoas específicas",
        "Equipe inteira"
    ],
    horizontal=True
)

if modo == "Categoria(s)":
    escolhidos = st.multiselect(
        "Selecione uma ou mais categorias",
        categorias,
        default=[]
    )
    selecionados = pessoas[pessoas["Categoria"].isin(escolhidos)]

elif modo == "Área(s)":
    if not areas_disponiveis:
        st.warning(
            "A planilha não possui áreas preenchidas. "
            "Verifique se existe uma coluna chamada 'Área' no formulário."
        )
        st.stop()

    escolhidos = st.multiselect(
        "Selecione uma ou mais áreas",
        areas_disponiveis
    )

    selecionados = pessoas[
        pessoas["Áreas"].apply(
            lambda lista_areas: any(
                area in escolhidos for area in lista_areas
            )
        )
    ]

elif modo == "Pessoas específicas":
    nomes = sorted(pessoas["Nome"].unique())
    escolhidos = st.multiselect("Selecione as pessoas", nomes)
    selecionados = pessoas[pessoas["Nome"].isin(escolhidos)]

else:
    selecionados = pessoas.copy()

if selecionados.empty:
    st.warning(
        "Selecione pelo menos uma categoria, área ou pessoa "
        "para visualizar os horários."
    )
    st.stop()

nomes_selecionados = selecionados["Nome"].tolist()
disp = disponibilidades[
    disponibilidades["Nome"].isin(nomes_selecionados)
].copy()
total = len(nomes_selecionados)

# -----------------------------------------------------------------------------
# Consulta detalhada: mostra todas as pessoas do grupo e separa quem marcou
# disponibilidade de quem não marcou aquele intervalo.
# -----------------------------------------------------------------------------
st.subheader("Consultar pessoas por horário")
st.caption(
    "Escolha um dia e um intervalo para conferir exatamente quem, dentro "
    "do grupo selecionado, marcou disponibilidade."
)

ordem_dias = list(DIAS.values())

def chave_horario(horario):
    """Retorna a hora inicial para ordenar intervalos como 8h-9h."""
    correspondencia = re.match(r"^(\d+)h", str(horario))
    return int(correspondencia.group(1)) if correspondencia else 99

# A lista de horários usa todas as respostas carregadas, não apenas o grupo
# filtrado. Assim, também é possível consultar horários em que ninguém do
# grupo selecionado marcou disponibilidade.
horarios_disponiveis_na_planilha = sorted(
    disponibilidades["Horário"].dropna().astype(str).unique().tolist(),
    key=chave_horario
)

if not horarios_disponiveis_na_planilha:
    st.warning(
        "Não foram encontrados horários válidos no arquivo. "
        "Confira se as respostas seguem o formato 8h-9h."
    )
else:
    col_dia, col_horario = st.columns(2)
    with col_dia:
        dia_consulta = st.selectbox(
            "Dia da semana",
            ordem_dias,
            key="consulta_detalhada_dia"
        )
    with col_horario:
        horario_consulta = st.selectbox(
            "Horário",
            horarios_disponiveis_na_planilha,
            key="consulta_detalhada_horario"
        )

    nomes_disponiveis = set(
        disp.loc[
            (disp["Dia"] == dia_consulta)
            & (disp["Horário"] == horario_consulta),
            "Nome"
        ].unique()
    )
    lista_disponiveis = sorted(nomes_disponiveis)
    lista_nao_disponiveis = sorted(
        set(nomes_selecionados) - nomes_disponiveis
    )

    metrica_disponiveis, metrica_nao_disponiveis, metrica_total = st.columns(3)
    metrica_disponiveis.metric(
        "Marcaram disponibilidade",
        len(lista_disponiveis)
    )
    metrica_nao_disponiveis.metric(
        "Não marcaram disponibilidade",
        len(lista_nao_disponiveis)
    )
    metrica_total.metric("Pessoas no grupo", total)

    coluna_disponiveis, coluna_nao_disponiveis = st.columns(2)
    with coluna_disponiveis:
        st.markdown("#### ✅ Disponíveis")
        if lista_disponiveis:
            st.dataframe(
                pd.DataFrame({"Nome": lista_disponiveis}),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * len(lista_disponiveis) + 40)
            )
        else:
            st.info("Ninguém do grupo marcou esse horário.")

    with coluna_nao_disponiveis:
        st.markdown("#### ❌ Não disponíveis")
        if lista_nao_disponiveis:
            st.dataframe(
                pd.DataFrame({"Nome": lista_nao_disponiveis}),
                use_container_width=True,
                hide_index=True,
                height=min(420, 38 * len(lista_nao_disponiveis) + 40)
            )
        else:
            st.success("Todas as pessoas do grupo marcaram esse horário.")

    st.caption(
        "‘Não disponíveis’ significa que essas pessoas não marcaram esse "
        "intervalo no formulário; não significa necessariamente que tenham "
        "registrado uma justificativa de indisponibilidade."
    )

# -----------------------------------------------------------------------------
# Ranking geral dos horários e mapa semanal.
# -----------------------------------------------------------------------------
st.subheader("Melhores horários")
st.write(
    f"Contagem considerando **{total} pessoa(s)** selecionada(s). "
    "Os horários são intervalos de uma hora."
)

ranking = pd.DataFrame(
    columns=["Dia", "Horário", "Pessoas disponíveis", "Percentual"]
)

if disp.empty:
    st.warning(
        "Nenhuma pessoa do grupo selecionado marcou disponibilidade. "
        "A consulta detalhada acima continua disponível para verificar os nomes."
    )
else:
    ranking = (
        disp.groupby(["Dia", "Horário"])["Nome"]
        .nunique()
        .rename("Pessoas disponíveis")
        .reset_index()
    )
    ranking["Percentual"] = (
        ranking["Pessoas disponíveis"] / total * 100
    )

    ranking["Dia"] = pd.Categorical(
        ranking["Dia"],
        categories=ordem_dias,
        ordered=True
    )
    ranking["_hora"] = ranking["Horário"].map(chave_horario)
    ranking = ranking.sort_values(
        ["Pessoas disponíveis", "Dia", "_hora"],
        ascending=[False, True, True]
    ).drop(columns="_hora")

    maximo = int(ranking["Pessoas disponíveis"].max())
    melhores = ranking[
        ranking["Pessoas disponíveis"] == maximo
    ]

    c1, c2 = st.columns(2)
    c1.metric(
        "Maior número de pessoas disponíveis",
        f"{maximo} de {total}"
    )
    c2.metric(
        "Quantidade de horários empatados no máximo",
        len(melhores)
    )

    st.dataframe(
        ranking.assign(
            Dia=ranking["Dia"].astype(str),
            **{
                "Disponibilidade": ranking["Percentual"].map(
                    lambda valor: f"{valor:.0f}%"
                )
            }
        )[[
            "Dia",
            "Horário",
            "Pessoas disponíveis",
            "Disponibilidade"
        ]],
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Mapa de disponibilidade")
    matriz = ranking.pivot(
        index="Dia",
        columns="Horário",
        values="Pessoas disponíveis"
    )
    matriz = matriz.reindex(ordem_dias)
    horarios_ordenados = sorted(
        matriz.columns,
        key=chave_horario
    )
    matriz = (
        matriz.reindex(columns=horarios_ordenados)
        .fillna(0)
        .astype(int)
    )
    st.dataframe(
        matriz,
        use_container_width=True
    )

if not ranking.empty:
    csv_saida = (
        ranking.assign(Dia=ranking["Dia"].astype(str))
        .to_csv(index=False)
        .encode("utf-8-sig")
    )
    st.download_button(
        "Baixar ranking em CSV",
        csv_saida,
        "ranking_disponibilidade.csv",
        "text/csv"
    )

with st.expander("Observações sobre os dados"):
    st.write(
        "A contagem considera cada pessoa uma única vez por intervalo. "
        "Se uma pessoa pertencer a mais de uma das áreas selecionadas, "
        "ela não será contada duas vezes. "
        "O programa interpreta intervalos no formato 8h-9h e ignora "
        "textos como 'Não tenho disponibilidade' sem descartar os "
        "outros horários válidos que estejam na mesma resposta."
    )
    if not areas_disponiveis:
        st.info(
            "Para consultar capacitações por área, adicione uma coluna "
            "'Área' à planilha e informe a(s) área(s) de cada pessoa."
        )
