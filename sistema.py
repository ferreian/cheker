import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import io
import tempfile
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
import logging

# Configurar sistema de logs


def setup_logging():
    """Configura sistema de logs"""
    logging.basicConfig(
        filename='material_checker.log',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def log_material_check(material_id, avanco_status, found, user_id="system"):
    """Registra checagem nos logs"""
    logging.info(
        f"Material check: ID={material_id}, Avanco={avanco_status}, Found={found}, User={user_id}")


def visual_feedback(feedback_type, material_data=None):
    """Feedback visual para o scanner"""
    if feedback_type == "found":
        st.markdown("""
        <div class="alert-success">
            <i class="alert-icon">✅</i>
            <div class="alert-content">
                <strong>Material Encontrado!</strong>
                <p>Item localizado com sucesso</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

    elif feedback_type == "error":
        st.markdown("""
        <div class="alert-error">
            <i class="alert-icon">❌</i>
            <div class="alert-content">
                <strong>Material Não Encontrado</strong>
                <p>Verifique o código e tente novamente</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Alert vermelho adicional para material não encontrado
        st.markdown("""
        <div class="trait-alert" style="
            background: #ef4444;
            color: #ffffff;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            margin: 1rem 0;
            text-align: center;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
        ">
            🔴 Material não localizado no sistema
        </div>
        """, unsafe_allow_html=True)

    elif feedback_type == "warning":
        st.markdown("""
        <div class="alert-error">
            <i class="alert-icon">❌</i>
            <div class="alert-content">
                <strong>Status de Avanço Incorreto</strong>
                <p>Material encontrado com avanço diferente</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

# Função para validar dados do Excel


def validate_excel_data(df):
    """Valida e limpa dados do Excel"""
    issues = []
    duplicated_ids = df[df['id_codigo'].duplicated()]
    if not duplicated_ids.empty:
        issues.append(
            f"IDs duplicados encontrados: {duplicated_ids['id_codigo'].tolist()}")

    null_ids = df[df['id_codigo'].isnull()]
    if not null_ids.empty:
        issues.append("Materiais com ID vazio encontrados")

    return issues

# Função para exportar relatórios


def export_report(df, check_history):
    """Exporta relatório completo da checagem"""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Materiais', index=False)
        if check_history:
            history_df = pd.DataFrame(check_history)
            history_df.to_excel(
                writer, sheet_name='Histórico_Checagens', index=False)
        stats = df['avanco'].value_counts().reset_index()
        stats.columns = ['Avanco', 'Quantidade']
        stats.to_excel(writer, sheet_name='Estatísticas', index=False)
    return buffer.getvalue()


def filter_materials(df, avanco_filter=None, id_search=None):
    """Filtra os materiais baseado nos critérios selecionados"""
    filtered_df = df.copy()
    if avanco_filter and avanco_filter != "Todos":
        filtered_df = filtered_df[filtered_df['avanco'] == avanco_filter]
    if id_search:
        mask = filtered_df['id_codigo'].astype(str).str.contains(
            str(id_search), case=False, na=False)
        if 'etapa_programa' in filtered_df.columns:
            mask |= filtered_df['etapa_programa'].astype(str).str.contains(
                str(id_search), case=False, na=False)
        filtered_df = filtered_df[mask]
    return filtered_df


def process_scan():
    """Callback executado quando o campo de scan muda"""
    scan_id = st.session_state.scanner_input

    if not scan_id or not scan_id.strip():
        return

    if hasattr(st.session_state, 'last_processed') and st.session_state.last_processed == scan_id.strip():
        return

    st.session_state.last_processed = scan_id.strip()
    scan_id_clean = scan_id.strip()
    current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    quick_avanco = st.session_state.get('current_quick_avanco', '')
    filtered_df = st.session_state.get('current_filtered_df', pd.DataFrame())

    if filtered_df.empty:
        return

    # Procurar pelo id_codigo
    material_matches = filtered_df[filtered_df['id_codigo'].astype(
        str) == scan_id_clean]

    if not material_matches.empty:
        material_row = material_matches.iloc[0]
        current_material_avanco = material_row['avanco']

        if current_material_avanco == quick_avanco:
            st.session_state.scanner_state = "found"
            st.session_state.current_material = scan_id_clean
            st.session_state.found_material_data = material_row.to_dict()
            st.session_state.scan_success = True
        else:
            st.session_state.check_history.append({
                'id_codigo': scan_id_clean,
                'etapa_programa': material_row.get('etapa_programa', 'Sem etapa'),
                'trait': material_row.get('trait', 'Sem trait'),
                'avanco': current_material_avanco,
                'check_time': current_time,
                'encontrado': 'Não - Avanço incorreto'
            })
            log_material_check(scan_id_clean, current_material_avanco, False)
            st.session_state.scan_error = f"Avanço incorreto! Esperado: {quick_avanco}, Atual: {current_material_avanco}"
    else:
        st.session_state.check_history.append({
            'id_codigo': scan_id_clean,
            'etapa_programa': 'Não encontrado',
            'trait': 'N/A',
            'avanco': 'N/A',
            'check_time': current_time,
            'encontrado': 'Não'
        })
        log_material_check(scan_id_clean, 'N/A', False)
        st.session_state.scan_error = f"ID '{scan_id_clean}' não encontrado!"

    st.session_state.scanner_input = ""


def load_excel_file(uploaded_file):
    """Carrega o arquivo Excel e valida as colunas obrigatórias"""
    try:
        df = pd.read_excel(uploaded_file)

        # Colunas obrigatórias adaptadas para seu arquivo
        required_columns = ['etapa_programa', 'id_codigo', 'avanco']
        missing_columns = [
            col for col in required_columns if col not in df.columns]

        if missing_columns:
            st.error(
                f"Colunas obrigatórias não encontradas: {missing_columns}")
            st.info(
                "O arquivo deve conter pelo menos as colunas: 'etapa_programa', 'id_codigo' e 'avanco'")
            return None

        # Adicionar coluna trait se não existir (para compatibilidade)
        if 'trait' not in df.columns:
            df['trait'] = 'N/A'

        issues = validate_excel_data(df)
        if issues:
            st.warning("⚠️ Problemas encontrados nos dados:")
            for issue in issues:
                st.write(f"• {issue}")
        return df

    except Exception as e:
        st.error(f"Erro ao carregar arquivo: {str(e)}")
        return None


def main():
    st.set_page_config(
        page_title="Material Checker Pro - Etapas de Programa",
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # CSS PROFISSIONAL E MODERNO
    st.markdown("""
    <style>
    /* Reset e configurações globais */
    .main > div {
        padding-top: 2rem;
    }
    
    /* Header principal */
    .main-header {
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
        color: white;
        padding: 2.5rem 2rem;
        border-radius: 15px;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        position: relative;
        overflow: hidden;
    }
    
    .main-header::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(45deg, rgba(255,255,255,0.1) 0%, transparent 100%);
        pointer-events: none;
    }
    
    .main-header h1 {
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .main-header p {
        font-size: 1.1rem;
        opacity: 0.9;
        margin-top: 0.5rem;
        font-weight: 300;
    }
    
    /* Cards de métricas */
    .metric-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        border: 1px solid #e1e8ed;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.1);
    }
    
    .metric-card::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: linear-gradient(45deg, #3b82f6, #1d4ed8);
    }
    
    .metric-label {
        font-size: 0.875rem;
        color: #64748b;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #1e293b;
        line-height: 1;
    }
    
    /* Alertas modernos */
    .alert-success, .alert-error, .alert-warning {
        display: flex;
        align-items: center;
        padding: 1rem 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
        animation: slideIn 0.3s ease-out;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    .alert-success {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
    }
    
    .alert-error {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        color: white;
    }
    
    .alert-warning {
        background: linear-gradient(135deg, #eab308 0%, #ca8a04 100%);
        color: white;
    }
    
    .alert-icon {
        font-size: 1.5rem;
        margin-right: 1rem;
        flex-shrink: 0;
    }
    
    .alert-content strong {
        display: block;
        font-size: 1.1rem;
        margin-bottom: 0.25rem;
    }
    
    .alert-content p {
        margin: 0;
        opacity: 0.9;
        font-size: 0.9rem;
    }
    
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    /* Scanner area */
    .scanner-area {
        background: white;
        border-radius: 15px;
        padding: 2rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        border: 1px solid #e1e8ed;
        margin: 2rem 0;
    }
    
    .scanner-status {
        background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 1.5rem;
        font-weight: 600;
        box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3);
    }
    
    /* Material found card */
    .material-found {
        background: white;
        border-radius: 15px;
        padding: 2rem;
        margin: 2rem auto;
        max-width: 500px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        border: 2px solid #10b981;
        text-align: center;
        animation: bounceIn 0.5s ease-out;
    }
    
    @keyframes bounceIn {
        0% {
            opacity: 0;
            transform: scale(0.3);
        }
        50% {
            opacity: 1;
            transform: scale(1.05);
        }
        70% {
            transform: scale(0.9);
        }
        100% {
            opacity: 1;
            transform: scale(1);
        }
    }
    
    .material-info {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #6b7280;
    }
    
    .material-info p {
        margin: 0.5rem 0;
        font-size: 1rem;
    }
    
    .material-info strong {
        color: #1e293b;
    }
    
    /* Botões profissionais */
    .stButton > button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.75rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4);
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
    }
    
    .stButton > button:active {
        transform: translateY(0);
    }
    
    /* Sidebar */
    .css-1d391kg {
        background: #f0fdf4;
    }
    
    /* Tables */
    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    
    /* Input fields */
    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 2px solid #e1e8ed;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        transition: all 0.3s ease;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #10b981;
        box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1);
    }
    
    /* Selectbox */
    .stSelectbox > div > div > select {
        border-radius: 8px;
        border: 2px solid #e1e8ed;
    }
    
    /* Sound indicator */
    .sound-indicator {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
        padding: 0.75rem 1.5rem;
        border-radius: 25px;
        text-align: center;
        margin: 1rem 0;
        font-weight: 600;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0% {
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }
        50% {
            box-shadow: 0 4px 20px rgba(16, 185, 129, 0.5);
        }
        100% {
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }
    }
    
    /* Progress bar customizado */
    .stProgress > div > div > div > div {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    }
    
    /* Responsividade */
    @media (max-width: 768px) {
        .main-header h1 {
            font-size: 2rem;
        }
        
        .metric-card {
            padding: 1rem;
        }
        
        .scanner-area {
            padding: 1.5rem;
            margin: 1rem 0;
        }
        
        .material-found {
            padding: 1.5rem;
            margin: 1rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # Inicializar sistema de logs
    setup_logging()

    # Header principal adaptado
    st.markdown("""
    <div class="main-header" style="background: #f8f9fa; color: #1e293b;">
        <h1>📦 Material Checker Pro</h1>
        <p>Sistema de Checagem</p>
    </div>
    """, unsafe_allow_html=True)

    # Inicializar estados da sessão
    session_defaults = {
        'check_history': [],
        'scanner_state': "ready",
        'current_material': None,
        'found_material_data': None,
        'show_animations': True,
        'scanner_input': "",
        'scan_success': False,
        'scan_error': None,
        'last_processed': ""
    }

    for key, default in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # Sidebar configurações
    with st.sidebar:
        st.markdown("### 📁 Configurações do Sistema")

        uploaded_file = st.file_uploader(
            "📄 Carregar Arquivo Excel",
            type=['xlsx', 'xls'],
            help="Arquivo deve conter as colunas: 'etapa_programa', 'id_codigo' e 'avanco'"
        )

        with st.expander("⚙️ Configurações Avançadas"):
            st.session_state.show_animations = st.checkbox(
                "🎬 Animações visuais",
                value=st.session_state.show_animations
            )

        # Processamento do arquivo
        df = None
        if uploaded_file is not None:
            df = load_excel_file(uploaded_file)
            if df is not None:
                st.success(f"✅ {len(df)} materiais carregados")

                st.markdown("#### 🔍 Filtros")
                avanco_options = ["Todos"] + \
                    sorted(df['avanco'].unique().tolist())
                avanco_filter = st.selectbox("Avanço:", avanco_options)
                search_term = st.text_input(
                    "Buscar:", placeholder="ID ou etapa...")
            else:
                st.error("❌ Erro no arquivo")
        else:
            st.info("👆 Faça upload do arquivo Excel")

    # Área principal
    if df is not None:
        # Aplicar filtros
        filtered_df = filter_materials(df,
                                       avanco_filter if 'avanco_filter' in locals() else None,
                                       search_term if 'search_term' in locals() else None)

        st.session_state.current_filtered_df = filtered_df

        # Estatísticas em cards modernos
        st.markdown("### 📊 Visão Geral dos Materiais")

        # Estatísticas por avanço
        avanco_counts = filtered_df['avanco'].value_counts()

        # Estatísticas por trait
        trait_counts = filtered_df['trait'].value_counts()

        # Definir cores para traits
        trait_colors = {
            'CE3': '#8b5cf6',
            'E3': '#10b981',
            'CONV': '#f59e0b'
        }

        # Cards de avanço
        if len(avanco_counts) > 0:
            st.markdown("#### 📈 Por Status de Avanço")
            cols = st.columns(len(avanco_counts))

            # Cores específicas para cada status de avanço
            avanco_colors = {
                'Sim': {'color': '#10b981', 'border': '#10b981'},  # Verde
                'Não': {'color': '#ef4444', 'border': '#ef4444'}   # Vermelho
            }

            for idx, (avanco, count) in enumerate(avanco_counts.items()):
                with cols[idx]:
                    # Usar cor específica ou padrão
                    color_config = avanco_colors.get(
                        avanco, {'color': '#6b7280', 'border': '#6b7280'})

                    st.markdown(f"""
                    <div class="metric-card" style="position: relative;">
                        <div style="position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: {color_config['border']}; border-radius: 2px 0 0 2px;"></div>
                        <div class="metric-label">{avanco}</div>
                        <div class="metric-value" style="color: {color_config['color']}">{count}</div>
                    </div>
                    """, unsafe_allow_html=True)

        # Cards de trait
        if len(trait_counts) > 0:
            st.markdown("#### 🎯 Por Tipo de Trait")
            trait_cols = st.columns(len(trait_counts))

            for idx, (trait, count) in enumerate(trait_counts.items()):
                with trait_cols[idx]:
                    # Usar cor específica do trait ou cinza padrão
                    trait_color = trait_colors.get(trait, '#6b7280')
                    trait_name = {
                        'CE3': 'CE3 (ROXO)',
                        'E3': 'E3 (VERDE)',
                        'CONV': 'CONV (LARANJA)'
                    }.get(trait, trait)

                    st.markdown(f"""
                    <div class="metric-card" style="border-left-color: {trait_color};">
                        <div class="metric-label">{trait_name}</div>
                        <div class="metric-value" style="color: {trait_color}">{count}</div>
                    </div>
                    """, unsafe_allow_html=True)

        # Tabela de materiais
        with st.expander(f"📋 Lista Completa ({len(filtered_df)} itens)", expanded=False):
            st.dataframe(filtered_df, use_container_width=True,
                         hide_index=True)

        # SEÇÃO DO SCANNER
        st.markdown('<div class="scanner-area">', unsafe_allow_html=True)

        all_avancos = sorted(filtered_df['avanco'].unique().tolist())
        if all_avancos:
            quick_avanco = st.selectbox(
                "🎯 Procurar materiais com avanço:",
                all_avancos,
                key="quick_avanco"
            )
            st.session_state.current_quick_avanco = quick_avanco

            # SCANNER LOGIC
            if st.session_state.scanner_state == "ready":
                st.markdown(
                    f'<div class="scanner-status" style="background: #f8f9fa; color: #1e293b;">🔍 Scanner Ativo - Procurando: {quick_avanco}</div>', unsafe_allow_html=True)

                # Mostrar mensagens de resultado
                if st.session_state.scan_success:
                    if st.session_state.show_animations:
                        visual_feedback("found")
                    st.session_state.scan_success = False

                if st.session_state.scan_error:
                    if "Avanço incorreto" in st.session_state.scan_error:
                        visual_feedback("warning")
                    else:
                        visual_feedback("error")
                    st.session_state.scan_error = None

                # Campo de input principal
                scan_id = st.text_input(
                    "📱 Digite ou escaneie o código do material:",
                    key="scanner_input",
                    placeholder="ID do material...",
                    help="⚡ Campo com limpeza automática",
                    on_change=process_scan
                )

            elif st.session_state.scanner_state == "found":
                material_data = st.session_state.found_material_data
                scan_id = st.session_state.current_material

                # Definir cores baseadas no trait
                trait_value = material_data.get('trait', 'N/A')
                trait_colors = {
                    'CE3': {'bg': '#8b5cf6', 'text': '#ffffff', 'name': 'CE3 (ROXO)'},
                    'E3': {'bg': '#10b981', 'text': '#ffffff', 'name': 'E3 (VERDE)'},
                    'CONV': {'bg': '#f59e0b', 'text': '#ffffff', 'name': 'CONV (LARANJA)'}
                }

                # Usar cor padrão se trait não for reconhecido
                color_config = trait_colors.get(
                    trait_value, {'bg': '#6b7280', 'text': '#ffffff', 'name': trait_value})

                st.markdown(f"""
                <div class="material-found">
                    <h3 style="color: #1e293b; margin-bottom: 1rem;">✅ Material Localizado!</h3>
                    <div class="material-info">
                        <p><strong>ID Código:</strong> {scan_id}</p>
                        <p style="font-size: 1.2rem; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;"><strong>ETAPA PROGRAMA:</strong> {material_data.get('etapa_programa', 'Não informado')}</p>
                        <p><strong>Trait:</strong> {color_config['name']}</p>
                        <p><strong>Avanço:</strong> {material_data['avanco']}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Alert colorido baseado no trait
                st.markdown(f"""
                <div class="trait-alert" style="
                    background: {color_config['bg']};
                    color: {color_config['text']};
                    padding: 1rem 1.5rem;
                    border-radius: 12px;
                    margin: 1rem 0;
                    text-align: center;
                    font-weight: 600;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                ">
                    🎯 Tipo: {color_config['name']}
                </div>
                """, unsafe_allow_html=True)

                # Botões de ação
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("✅ Confirmar", type="primary", key="confirm_btn", use_container_width=True):
                        current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                        st.session_state.check_history.append({
                            'id_codigo': scan_id,
                            'etapa_programa': material_data.get('etapa_programa', 'Sem etapa'),
                            'trait': material_data.get('trait', 'N/A'),
                            'avanco': material_data['avanco'],
                            'check_time': current_time,
                            'encontrado': 'Sim'
                        })

                        log_material_check(
                            scan_id, material_data['avanco'], True)

                        st.balloons()

                        # Reset scanner
                        st.session_state.scanner_state = "ready"
                        st.session_state.current_material = None
                        st.session_state.found_material_data = None
                        st.session_state.scanner_input = ""
                        st.session_state.last_processed = ""

                        st.rerun()

                with col2:
                    if st.button("⏭️ Pular", key="skip_btn", use_container_width=True):
                        # Reset sem salvar
                        st.session_state.scanner_state = "ready"
                        st.session_state.current_material = None
                        st.session_state.found_material_data = None
                        st.session_state.scanner_input = ""
                        st.session_state.last_processed = ""
                        st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

        # HISTÓRICO E ESTATÍSTICAS
        if st.session_state.check_history:
            st.markdown("---")

            # Estatísticas da checagem
            st.markdown("### 📈 Estatísticas da Checagem")

            if 'quick_avanco' in locals():
                total_materials_avanco = len(
                    filtered_df[filtered_df['avanco'] == quick_avanco])
                encontrados = len([h for h in st.session_state.check_history
                                   if h['encontrado'] == 'Sim' and h['avanco'] == quick_avanco])
                faltantes = total_materials_avanco - encontrados

                # Progress bar
                if total_materials_avanco > 0:
                    progress = encontrados / total_materials_avanco
                    st.progress(
                        progress, text=f"Progresso: {encontrados}/{total_materials_avanco} ({progress:.1%})")

                # Métricas em cards
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">Total com Avanço</div>
                        <div class="metric-value" style="color: #3b82f6">{total_materials_avanco}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">Verificados</div>
                        <div class="metric-value" style="color: #1d4ed8">{encontrados}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col3:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">Faltantes</div>
                        <div class="metric-value" style="color: #2563eb">{faltantes}</div>
                    </div>
                    """, unsafe_allow_html=True)

            # Histórico detalhado
            with st.expander("📋 Histórico Detalhado de Checagens", expanded=True):
                history_df = pd.DataFrame(st.session_state.check_history)

                # Configurar cores das colunas
                def color_status(val):
                    if val == 'Sim':
                        return 'background-color: #dcfce7; color: #166534'
                    elif 'incorreto' in str(val):
                        return 'background-color: #fef3c7; color: #92400e'
                    else:
                        return 'background-color: #fef2f2; color: #dc2626'

                styled_df = history_df.style.applymap(
                    color_status, subset=['encontrado'])
                st.dataframe(styled_df, use_container_width=True,
                             hide_index=True)

            # Controles e ações
            st.markdown("### 🛠️ Controles do Sistema")
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("🗑️ Limpar Histórico", use_container_width=True):
                    st.session_state.check_history = []
                    st.success("✅ Histórico limpo!")
                    st.rerun()

            with col2:
                if st.button("🔄 Resetar Scanner", use_container_width=True):
                    # Reset completo
                    reset_keys = ['scanner_state', 'current_material', 'found_material_data',
                                  'scanner_input', 'last_processed', 'scan_error', 'scan_success']
                    for key in reset_keys:
                        if key == 'scanner_state':
                            st.session_state[key] = "ready"
                        elif key in ['scan_error', 'scan_success']:
                            st.session_state[key] = None if key == 'scan_error' else False
                        else:
                            st.session_state[key] = "" if 'input' in key or 'processed' in key else None

                    st.success("✅ Scanner resetado!")
                    st.rerun()

            with col3:
                # Botão de exportação
                report_data = export_report(
                    filtered_df, st.session_state.check_history)
                st.download_button(
                    label="📊 Exportar Relatório",
                    data=report_data,
                    file_name=f"relatorio_checagem_etapas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

        # Footer profissional
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; padding: 2rem; color: #64748b; font-size: 0.9rem;">
            <p><strong>Material Checker Pro</strong> • Sistema de Checagem de Materiais</p>
            <p>Desenvolvido por <a href="https://www.linkedin.com/in/eng-agro-andre-ferreira/" target="_blank" style="color: #3b82f6; text-decoration: none; font-weight: 600;">Andre Ferreira</a> • © 2025</p>
        </div>
        """, unsafe_allow_html=True)

    else:
        # Tela de boas-vindas quando não há arquivo
        st.markdown("""
        <div style="text-align: center; padding: 4rem 2rem; background: white; border-radius: 15px; margin: 2rem 0; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">
            <h2 style="color: #1e293b; margin-bottom: 1rem;">👋 Bem-vindo ao Material Checker Pro</h2>
            <p style="color: #64748b; font-size: 1.1rem; margin-bottom: 2rem;">
                Sistema para checagem e controle de etapas de programa com scanner digital
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Instruções em formato nativo do Streamlit
        st.markdown("### 🚀 Para começar:")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.info("""
            **Passos para usar o sistema:**
            
            1. 📁 Faça upload do arquivo Excel na barra lateral
            2. ✅ Certifique-se que contém as colunas: 'etapa_programa', 'id_codigo' e 'avanco'  
            3. ⚙️ Configure o avanço desejado para checagem
            4. 📱 Use o scanner ou digite os códigos manualmente
            """)

        # Features em colunas
        st.markdown("### ✨ Recursos Principais")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown("""
            <div style="text-align: center; padding: 1.5rem; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📱</div>
                <h4>Scanner Digital</h4>
                <p style="color: #64748b;">Leitura automática de códigos</p>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown("""
            <div style="text-align: center; padding: 1.5rem; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📊</div>
                <h4>Relatórios</h4>
                <p style="color: #64748b;">Estatísticas em tempo real</p>
            </div>
            """, unsafe_allow_html=True)

        with col3:
            st.markdown("""
            <div style="text-align: center; padding: 1.5rem; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">🎯</div>
                <h4>Controle de Avanço</h4>
                <p style="color: #64748b;">Verificação por status</p>
            </div>
            """, unsafe_allow_html=True)

        with col4:
            st.markdown("""
            <div style="text-align: center; padding: 1.5rem; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📋</div>
                <h4>Histórico</h4>
                <p style="color: #64748b;">Registro de checagens</p>
            </div>
            """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
