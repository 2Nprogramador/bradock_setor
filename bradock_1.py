import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
from google.oauth2.service_account import Credentials
import json
import toml

scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Credenciais do Streamlit Secrets
creds_dict = st.secrets["google_sheets_credentials"]

# Obter as credenciais do serviço
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
client = gspread.authorize(creds)

@st.cache_data(ttl=3)
# Função para inicializar os DataFrames a partir da Google Sheets
def init_dataframes():
    try:
        vendas_sheet = client.open("vendas").worksheet("vendas")
        vendas_df = pd.DataFrame(vendas_sheet.get_all_records())
        if vendas_df.empty:
            vendas_df = pd.DataFrame(columns=["Código da Venda", "Produto", "Lote", "Quantidade",
                                              "Método de Pagamento", "Data da Venda", "Valor Unitário (R$)",
                                              "Valor Total (R$)"])
    except gspread.exceptions.WorksheetNotFound:
        vendas_df = pd.DataFrame(columns=["Código da Venda", "Produto", "Lote", "Quantidade",
                                          "Método de Pagamento", "Data da Venda", "Valor Unitário (R$)",
                                          "Valor Total (R$)"])

    try:
        registro_estoque_sheet = client.open("registro_estoque").worksheet("registro_estoque")
        registro_estoque_df = pd.DataFrame(registro_estoque_sheet.get_all_records())
        if registro_estoque_df.empty:
            registro_estoque_df = pd.DataFrame(columns=["Produto", "Lote", "Quantidade", "Setor", "Data de Entrada",
                                                        "Data de Validade", "Custo (R$)", "Valor de Venda (R$)"])
    except gspread.exceptions.WorksheetNotFound:
        registro_estoque_df = pd.DataFrame(columns=["Produto", "Lote", "Quantidade", "Setor", "Data de Entrada",
                                                    "Data de Validade", "Custo (R$)", "Valor de Venda (R$)"])

    return vendas_df, registro_estoque_df


# Carregar os DataFrames das planilhas
vendas_df, registro_estoque_df = init_dataframes()


# Salvar os DataFrames nas planilhas Google
def salvar_dados():
    if 'Data de Entrada' in registro_estoque_df.columns:
        registro_estoque_df['Data de Entrada'] = registro_estoque_df['Data de Entrada'].astype(str)
    if 'Data de Validade' in registro_estoque_df.columns:
        registro_estoque_df['Data de Validade'] = registro_estoque_df['Data de Validade'].astype(str)
    if 'Data da Venda' in vendas_df.columns:
        vendas_df['Data da Venda'] = vendas_df['Data da Venda'].astype(str)

    float_columns = ["Custo (R$)", "Valor de Venda (R$)", "Valor Unitário (R$)", "Valor Total (R$)"]
    for col in float_columns:
        if col in registro_estoque_df.columns:
            registro_estoque_df[col] = registro_estoque_df[col].apply(
                lambda x: f"{x:.2f}".replace(",", ".") if pd.notnull(x) else x)
        if col in vendas_df.columns:
            vendas_df[col] = vendas_df[col].apply(lambda x: f"{x:.2f}".replace(",", ".") if pd.notnull(x) else x)

    vendas_sheet = client.open("vendas").worksheet("vendas")
    vendas_sheet.update([vendas_df.columns.values.tolist()] + vendas_df.values.tolist())

    registro_estoque_sheet = client.open("registro_estoque").worksheet("registro_estoque")
    registro_estoque_sheet.update([registro_estoque_df.columns.values.tolist()] + registro_estoque_df.values.tolist())
    init_dataframes()


# Função para calcular o estoque atualizado
def calcular_estoque_atualizado():
    estoque_entrada = registro_estoque_df.groupby(["Produto", "Lote"], as_index=False)["Quantidade"].sum()
    vendas = vendas_df.groupby(["Produto", "Lote"], as_index=False)["Quantidade"].sum()
    vendas["Quantidade"] *= -1
    estoque_atualizado_df = pd.merge(estoque_entrada, vendas, on=["Produto", "Lote"], how="outer",
                                     suffixes=("_entrada", "_venda"))
    estoque_atualizado_df.fillna(0, inplace=True)
    estoque_atualizado_df["Saldo"] = estoque_atualizado_df["Quantidade_entrada"] + estoque_atualizado_df[
        "Quantidade_venda"]
    estoque_atualizado_df = pd.merge(estoque_atualizado_df, registro_estoque_df[
        ["Produto", "Lote", "Data de Entrada", "Data de Validade", "Custo (R$)", "Setor"]],
                                     on=["Produto", "Lote"], how="left")
    estoque_atualizado_df["Custos Totais"] = estoque_atualizado_df["Saldo"] * estoque_atualizado_df["Custo (R$)"]
    estoque_atualizado_df.loc[estoque_atualizado_df["Saldo"] == 0, "Data de Validade"] = ""
    return estoque_atualizado_df


# Página de Entrada de Estoque
def entrada_estoque():
    global registro_estoque_df

    senha_armazenada = st.secrets["auth"]["senha_armazenada"]
    entrada_senha = st.sidebar.text_input("Digite a senha para acessar entrada de estoque:", type="password")

    if entrada_senha == senha_armazenada:
        st.header("Entrada de Estoque")
        produto = st.text_input("Nome do Produto").upper()
        quantidade = st.number_input("Quantidade", min_value=0, step=1)
        setor = st.text_input("Setor do Produto").upper()
        data_entrada = datetime.today().date()
        data_validade = st.date_input("Data de Validade")
        custo = st.number_input("Custo do Produto (R$)")
        valor_venda = st.number_input("Valor de Venda (R$)")

        if produto in registro_estoque_df["Produto"].values:
            ultimo_lote = (
                registro_estoque_df.loc[registro_estoque_df["Produto"] == produto, "Lote"]
                .str.extract(r"(\d+)").astype(int).max().values[0]
            )
            lote = f"LOTE {ultimo_lote + 1}"
        else:
            lote = "LOTE 1"

        if st.button("Adicionar ao Estoque"):
            novo_produto = pd.DataFrame(
                {
                    "Produto": [produto],
                    "Lote": [lote],
                    "Quantidade": [quantidade],
                    "Setor": [setor],
                    "Data de Entrada": [data_entrada],
                    "Data de Validade": [data_validade],
                    "Custo (R$)": [custo],
                    "Valor de Venda (R$)": [valor_venda],
                }
            )
            registro_estoque_df = pd.concat([registro_estoque_df, novo_produto], ignore_index=True)

            salvar_dados()
            vendas_df, registro_estoque_df = init_dataframes()
            st.success(f"{quantidade} unidades de '{produto}' (Lote: {lote}, Setor: {setor}) adicionadas ao estoque.")
    else:
        st.warning("Senha incorreta! Acesso negado à entrada de estoque.")


# Página de Visualização de Dados
def visualizar_dados():
    vendas_df, registro_estoque_df = init_dataframes()

    senha_armazenada = st.secrets["auth"]["senha_armazenada"]
    entrada_senha = st.sidebar.text_input("Digite a senha para visualizar dados:", type="password")

    if entrada_senha == senha_armazenada:
        st.header("Registro de Estoque")
        st.dataframe(registro_estoque_df)

        st.header("Vendas")
        st.dataframe(vendas_df)

        st.header("Estoque Atualizado")
        estoque_atualizado_df = calcular_estoque_atualizado()
        st.dataframe(estoque_atualizado_df)
    else:
        st.warning("Senha incorreta! Acesso negado à visualização de dados.")


# Navegação
page = st.sidebar.radio("Selecione uma opção", options=["Entrada de Estoque", "Visualizar Dados"])
vendas_df, registro_estoque_df = init_dataframes()

if page == "Entrada de Estoque":
    entrada_estoque()
elif page == "Visualizar Dados":
    visualizar_dados()