import streamlit as st
import pandas as pd
import numpy as np
import datetime
import pytz
import matplotlib.pyplot as plt
import time
import requests
from datetime import datetime, timedelta, date
from scipy.stats import norm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

# Configuración de la página
st.set_page_config(
    page_title="Gamma Exposure Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título principal
st.title("📊 Gamma Exposure Analysis")
st.markdown("---")

# Sidebar para parámetros
st.sidebar.header("🎯 Parámetros de Análisis")
ticker = st.sidebar.text_input("Ticker Symbol", value="SPX", help="Ejemplo: SPX, VIX, etc.")
width = st.sidebar.number_input("Width (puntos)", min_value=50, max_value=500, value=150, step=10, 
                                help="Rango de strikes alrededor del spot price")

# Botón para ejecutar análisis
if st.sidebar.button("🚀 Ejecutar Análisis", type="primary"):
    
    # Función para calcular Gamma Exposure basado en Black-Scholes
    @st.cache_data
    def calcGammaEx(S, K, vol, T, r, q, optType, OI):
        if T == 0 or vol == 0:
            return 0

        dp = (np.log(S/K) + (r - q + 0.5*vol**2)*T) / (vol*np.sqrt(T))
        dm = dp - vol*np.sqrt(T) 

        if optType == 'call':
            gamma = np.exp(-q*T) * norm.pdf(dp) / (S * vol * np.sqrt(T))
            return OI * 100 * S * S * 0.01 * gamma 
        else:  # Gamma is same for calls and puts
            gamma = K * np.exp(-r*T) * norm.pdf(dm) / (S * S * vol * np.sqrt(T))
            return OI * 100 * S * S * 0.01 * gamma 

    # Función para detectar el tercer viernes del mes
    def isThirdFriday(d):
        return d.weekday() == 4 and 15 <= d.day <= 21

    try:
        # Mostrar spinner durante la carga
        with st.spinner(f'Descargando datos para {ticker}...'):
            
            # Descargar datos desde CBOE
            url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{ticker}.json"
            response = requests.get(url)
            
            if response.status_code != 200:
                st.error(f"Error al descargar datos para {ticker}. Código de estado: {response.status_code}")
                st.stop()
                
            options = response.json()
            
            # Spot Price
            spotPrice = options["data"]["close"]
            spot = spotPrice
            
            # Mostrar información del spot
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("💰 Spot Price", f"${spotPrice:,.2f}")
            with col2:
                st.metric("🎯 Ticker", ticker)
            with col3:
                st.metric("📏 Width", f"±{width} pts")
            
            st.markdown("---")
            
            fromStrike = 0.8 * spotPrice
            toStrike = 1.2 * spotPrice

            # Cargar datos en DataFrame
            data_df = pd.DataFrame(options["data"]["options"])

            data_df['CallPut'] = data_df['option'].str.slice(start=-9,stop=-8)
            data_df['ExpirationDate'] = data_df['option'].str.slice(start=-15,stop=-9)
            data_df['ExpirationDate'] = pd.to_datetime(data_df['ExpirationDate'], format='%y%m%d')
            data_df['Strike'] = data_df['option'].str.slice(start=-8,stop=-3).str.lstrip('0')

            # Separar calls y puts
            data_df_calls = data_df.loc[data_df['CallPut'] == "C"].reset_index(drop=True)
            data_df_puts = data_df.loc[data_df['CallPut'] == "P"].reset_index(drop=True)

            # Construir DataFrame combinado calls y puts
            df_calls = data_df_calls[['ExpirationDate','option','last_trade_price','change','bid','ask','volume','iv','delta','gamma','open_interest','Strike']]
            df_puts = data_df_puts[['ExpirationDate','option','last_trade_price','change','bid','ask','volume','iv','delta','gamma','open_interest','Strike']]
            df_puts.columns = ['put_exp','put_option','put_last_trade_price','put_change','put_bid','put_ask','put_volume','put_iv','put_delta','put_gamma','put_open_interest','put_strike']

            df = pd.concat([df_calls, df_puts], axis=1)

            # Verificar que las expiraciones y strikes coinciden
            df['check'] = np.where((df['ExpirationDate'] == df['put_exp']) & (df['Strike'] == df['put_strike']), 0, 1)
            if df['check'].sum() != 0:
                st.error("PUT CALL MERGE FAILED - OPTIONS ARE MISMATCHED.")
                st.stop()

            df.drop(['put_exp', 'put_strike', 'check'], axis=1, inplace=True)

            # Renombrar columnas para mejor claridad
            df.columns = ['ExpirationDate','Calls','CallLastSale','CallNet','CallBid','CallAsk','CallVol',
                          'CallIV','CallDelta','CallGamma','CallOpenInt','StrikePrice','Puts','PutLastSale',
                          'PutNet','PutBid','PutAsk','PutVol','PutIV','PutDelta','PutGamma','PutOpenInt']

            # Tipos y formatos
            df['ExpirationDate'] = pd.to_datetime(df['ExpirationDate'])
            df['ExpirationDate'] = df['ExpirationDate'] + timedelta(hours=16)
            df['StrikePrice'] = df['StrikePrice'].astype(float)
            df['CallIV'] = df['CallIV'].astype(float)
            df['PutIV'] = df['PutIV'].astype(float)
            df['CallGamma'] = df['CallGamma'].astype(float)
            df['PutGamma'] = df['PutGamma'].astype(float)
            df['CallOpenInt'] = df['CallOpenInt'].astype(float)
            df['PutOpenInt'] = df['PutOpenInt'].astype(float)

            # Calcular Gamma Exposure
            df['CallGEX'] = df['CallGamma'] * df['CallOpenInt'] * 100 * spotPrice * spotPrice * 0.01
            df['PutGEX'] = df['PutGamma'] * df['PutOpenInt'] * 100 * spotPrice * spotPrice * 0.01 * -1
            df['TotalGamma'] = (df.CallGEX + df.PutGEX) / 10**9

            dfAgg = df.groupby(['StrikePrice']).sum(numeric_only=True)
            strikes = dfAgg.index.values

            # === GRÁFICO 1: Total Gamma Exposure ===
            st.subheader("📊 Total Gamma Exposure")
            
            fig1 = go.Figure()
            fig1.add_trace(go.Bar(
                x=strikes,
                y=dfAgg['TotalGamma'].to_numpy(),
                name="Gamma Exposure",
                marker_color='lightblue',
                marker_line_color='black',
                marker_line_width=0.5
            ))
            
            fig1.add_vline(x=spotPrice, line_dash="dash", line_color="red", 
                          annotation_text=f"{ticker} Spot: {spotPrice:,.0f}")
            
            fig1.update_layout(
                title=f"Total Gamma: ${df['TotalGamma'].sum():.2f} Bn per 1% {ticker} Move",
                xaxis_title="Strike",
                yaxis_title="Spot Gamma Exposure ($ billions/1% move)",
                showlegend=True,
                height=500,
                xaxis_range=[fromStrike, toStrike]
            )
            
            st.plotly_chart(fig1, use_container_width=True)

            # === GRÁFICO 2: Open Interest ===
            st.subheader("📈 Open Interest - Calls vs Puts")
            
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=strikes,
                y=dfAgg['CallOpenInt'].to_numpy(),
                name="Call OI",
                marker_color='green',
                marker_line_color='black',
                marker_line_width=0.5
            ))
            fig2.add_trace(go.Bar(
                x=strikes,
                y=-1 * dfAgg['PutOpenInt'].to_numpy(),
                name="Put OI",
                marker_color='red',
                marker_line_color='black',
                marker_line_width=0.5
            ))
            
            fig2.add_vline(x=spotPrice, line_dash="dash", line_color="red",
                          annotation_text=f"{ticker} Spot: {spotPrice:,.0f}")
            
            fig2.update_layout(
                title=f"Total Open Interest for {ticker}",
                xaxis_title="Strike",
                yaxis_title="Open Interest (number of contracts)",
                showlegend=True,
                height=500,
                xaxis_range=[fromStrike, toStrike]
            )
            
            st.plotly_chart(fig2, use_container_width=True)

            # === PERFIL GAMMA EXPOSURE ===
            st.subheader("🎯 Perfil de Gamma Exposure")
            
            levels = np.linspace(fromStrike, toStrike, 30)
            todayDate = date.today()
            df['daysTillExp'] = [1/262 if (np.busday_count(todayDate, x.date())) == 0 else np.busday_count(todayDate, x.date())/262 for x in df.ExpirationDate]

            nextExpiry = df['ExpirationDate'].min()
            df['IsThirdFriday'] = [isThirdFriday(x) for x in df.ExpirationDate]
            thirdFridays = df.loc[df['IsThirdFriday'] == True]
            nextMonthlyExp = thirdFridays['ExpirationDate'].min()

            totalGamma = []
            totalGammaExNext = []
            totalGammaExFri = []

            for level in levels:
                df['callGammaEx'] = df.apply(lambda row: calcGammaEx(level, row['StrikePrice'], row['CallIV'], 
                                                                    row['daysTillExp'], 0, 0, "call", row['CallOpenInt']), axis=1)
                df['putGammaEx'] = df.apply(lambda row: calcGammaEx(level, row['StrikePrice'], row['PutIV'], 
                                                                   row['daysTillExp'], 0, 0, "put", row['PutOpenInt']), axis=1)    

                totalGamma.append(df['callGammaEx'].sum() - df['putGammaEx'].sum())

                exNxt = df.loc[df['ExpirationDate'] != nextExpiry]
                totalGammaExNext.append(exNxt['callGammaEx'].sum() - exNxt['putGammaEx'].sum())

                exFri = df.loc[df['ExpirationDate'] != nextMonthlyExp]
                totalGammaExFri.append(exFri['callGammaEx'].sum() - exFri['putGammaEx'].sum())

            totalGamma = np.array(totalGamma) / 10**9
            totalGammaExNext = np.array(totalGammaExNext) / 10**9
            totalGammaExFri = np.array(totalGammaExFri) / 10**9

            # Encontrar punto de flip gamma
            zeroCrossIdx = np.where(np.diff(np.sign(totalGamma)))[0]
            if len(zeroCrossIdx) > 0:
                negGamma = totalGamma[zeroCrossIdx]
                posGamma = totalGamma[zeroCrossIdx+1]
                negStrike = levels[zeroCrossIdx]
                posStrike = levels[zeroCrossIdx+1]
                zeroGamma = posStrike - ((posStrike - negStrike) * posGamma/(posGamma - negGamma))
                zeroGamma = zeroGamma[0]
            else:
                zeroGamma = None

            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=levels, y=totalGamma, mode='lines', name='All Expiries', line=dict(color='blue')))
            fig3.add_trace(go.Scatter(x=levels, y=totalGammaExNext, mode='lines', name='Ex-Next Expiry', line=dict(color='orange')))
            fig3.add_trace(go.Scatter(x=levels, y=totalGammaExFri, mode='lines', name='Ex-Next Monthly Expiry', line=dict(color='green')))
            
            fig3.add_vline(x=spotPrice, line_dash="dash", line_color="red",
                          annotation_text=f"{ticker} Spot: {spotPrice:,.0f}")
            
            if zeroGamma is not None:
                fig3.add_vline(x=zeroGamma, line_dash="dash", line_color="green",
                              annotation_text=f"Gamma Flip: {zeroGamma:,.0f}")
            
            fig3.add_hline(y=0, line_dash="solid", line_color="grey")
            
            fig3.update_layout(
                title=f"Gamma Exposure Profile, {ticker}, {todayDate.strftime('%d %b %Y')}",
                xaxis_title="Index Price",
                yaxis_title="Gamma Exposure ($ billions/1% move)",
                showlegend=True,
                height=500,
                xaxis_range=[fromStrike, toStrike]
            )
            
            st.plotly_chart(fig3, use_container_width=True)

            # === PROCESAMIENTO GEX FILTRADO ===
            required_cols = ['CallGamma', 'CallOpenInt', 'PutGamma', 'PutOpenInt', 'StrikePrice']
            for col in required_cols:
                if col not in df.columns:
                    df[col] = np.nan

            # Calcular GEX
            mult = 100 * 100
            df['call_gex'] = df['CallGamma'] * df['CallOpenInt'] * mult
            df['put_gex'] = df['PutGamma'] * df['PutOpenInt'] * mult
            df['net_gex'] = df['call_gex'] - df['put_gex']

            # Filtro ±width puntos desde el spot
            lower_bound = spot - width
            upper_bound = spot + width

            df_filtered = df[
                (df['net_gex'].notna()) &
                (df['StrikePrice'].notna()) &
                (df['StrikePrice'] >= lower_bound) &
                (df['StrikePrice'] <= upper_bound)
            ].sort_values(by='StrikePrice').reset_index(drop=True)

            # Identificar máximo y mínimo GEX
            max_gex = df_filtered.loc[df_filtered['net_gex'].idxmax()]
            min_gex = df_filtered.loc[df_filtered['net_gex'].idxmin()]
            pos = df_filtered[df_filtered['net_gex'] > 0]
            neg = df_filtered[df_filtered['net_gex'] < 0]

            # Calcular OI total y zonas de alto interés abierto
            df_filtered['total_oi'] = df_filtered['CallOpenInt'] + df_filtered['PutOpenInt']
            oi_threshold = np.percentile(df_filtered['total_oi'], 75)
            high_oi = df_filtered[df_filtered['total_oi'] >= oi_threshold]

            # === GRÁFICO 4: GEX por Strike ===
            st.subheader("⚡ GEX por Strike")
            
            fig4 = go.Figure()
            if len(pos) > 0:
                fig4.add_trace(go.Bar(
                    x=pos['StrikePrice'],
                    y=pos['net_gex'],
                    name='GEX Positivo',
                    marker_color='limegreen',
                    marker_line_color='black',
                    marker_line_width=0.8
                ))
            
            if len(neg) > 0:
                fig4.add_trace(go.Bar(
                    x=neg['StrikePrice'],
                    y=neg['net_gex'],
                    name='GEX Negativo',
                    marker_color='red',
                    marker_line_color='black',
                    marker_line_width=0.8
                ))
            
            fig4.add_hline(y=0, line_dash="dash", line_color="black")
            fig4.add_vline(x=spot, line_dash="dash", line_color="black")
            
            fig4.update_layout(
                title=f'{ticker} GEX x STK (±{width} pts del Spot {int(spot)})',
                xaxis_title="Strike",
                yaxis_title="Net GEX",
                showlegend=True,
                height=500
            )
            
            st.plotly_chart(fig4, use_container_width=True)

            # === GRÁFICO 5: Open Interest Total ===
            st.subheader("📊 Open Interest Total por Strike")
            
            fig5 = go.Figure()
            fig5.add_trace(go.Bar(
                x=df_filtered['StrikePrice'],
                y=df_filtered['total_oi'],
                name='Open Interest Total',
                marker_color='orange',
                marker_line_color='black',
                marker_line_width=0.8
            ))
            
            fig5.add_vline(x=spot, line_dash="dash", line_color="black")
            
            fig5.update_layout(
                title=f'OIT x Strike (±{width} pts del Spot {int(spot)})',
                xaxis_title="Strike",
                yaxis_title="Open Interest Total",
                showlegend=True,
                height=500
            )
            
            st.plotly_chart(fig5, use_container_width=True)

            # === GRÁFICO 6: Zonas Gamma ===
            st.subheader("🎯 Zonas Clave Gamma y Open Interest")
            
            # Información clave
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("🔴 Mín GEX", f"{int(min_gex['StrikePrice'])}")
            with col2:
                st.metric("🟢 Máx GEX", f"{int(max_gex['StrikePrice'])}")
            with col3:
                st.metric("📍 Spot", f"{int(spot)}")
            with col4:
                zona_gamma = abs(max_gex['StrikePrice'] - min_gex['StrikePrice'])
                st.metric("📏 Zona Gamma", f"{zona_gamma:.0f} pts")

            # Filtro más estricto para picos de OI
            threshold_oi = high_oi['total_oi'].quantile(0.90)
            high_oi_filtered = high_oi[high_oi['total_oi'] >= threshold_oi]

            # Crear gráfico de zonas
            fig6 = go.Figure()
            
            # Zona gamma (área sombreada)
            fig6.add_vrect(
                x0=min_gex['StrikePrice'], x1=max_gex['StrikePrice'],
                fillcolor="lightgreen", opacity=0.3,
                layer="below", line_width=0
            )
            
            # Líneas verticales para picos de OI
            for _, row in high_oi_filtered.iterrows():
                strike = row['StrikePrice']
                fig6.add_vline(x=strike, line_dash="dash", line_color="orange", opacity=0.6)
            
            # Línea vertical para spot
            fig6.add_vline(x=spot, line_dash="dash", line_color="black", line_width=2)
            
            fig6.update_layout(
                title='Zonas clave Gamma y Open Interest',
                xaxis_title="Strike",
                yaxis_title="Nivel",
                showlegend=True,
                height=500,
                xaxis_range=[min_gex['StrikePrice'] - 200, max_gex['StrikePrice'] + 200]
            )
            
            st.plotly_chart(fig6, use_container_width=True)

            # === GRÁFICO 7: Gamma Acumulado ===
            st.subheader("📈 Gamma Exposure Acumulado")
            
            df_sorted = df_filtered.sort_values(by='StrikePrice').reset_index(drop=True)
            df_sorted['cumulative_gex'] = df_sorted['net_gex'].cumsum()

            fig7 = go.Figure()
            
            # Zona gamma
            fig7.add_vrect(
                x0=min_gex['StrikePrice'], x1=max_gex['StrikePrice'],
                fillcolor="lightgreen", opacity=0.3,
                layer="below", line_width=0
            )
            
            # Barras de GEX neto
            fig7.add_trace(go.Bar(
                x=df_sorted['StrikePrice'],
                y=df_sorted['net_gex'],
                name='GEX Neto',
                marker_color='lightblue',
                opacity=0.5
            ))
            
            # Línea de GEX acumulado
            fig7.add_trace(go.Scatter(
                x=df_sorted['StrikePrice'],
                y=df_sorted['cumulative_gex'],
                mode='lines',
                name='GEX Acumulado',
                line=dict(color='blue', width=2)
            ))
            
            # Línea vertical spot
            fig7.add_vline(x=spot, line_dash="dash", line_color="black", line_width=2)
            
            fig7.update_layout(
                title=f'{ticker} Gamma Exposure Acumulado (Cumulative GEX)',
                xaxis_title="Strike",
                yaxis_title="GEX Acumulado",
                showlegend=True,
                height=500,
                xaxis_range=[min_gex['StrikePrice'] - 200, max_gex['StrikePrice'] + 200]
            )
            
            st.plotly_chart(fig7, use_container_width=True)

            # === RECOMENDACIONES ===
            st.subheader("💡 Recomendaciones para 0DTE")
            
            # Determinar si está dentro o fuera de la zona gamma
            if min_gex['StrikePrice'] <= spot <= max_gex['StrikePrice']:
                zona_status = "🟢 DENTRO de la zona gamma"
                zona_desc = "Probable consolidación y menor volatilidad"
            else:
                zona_status = "🔴 FUERA de la zona gamma"
                zona_desc = "Posible movimiento brusco o alta volatilidad"
            
            st.info(f"**Status actual**: El precio spot está {zona_status}, lo que indica {zona_desc}.")
            
            recomendaciones = """
            **📋 Estrategias Recomendadas:**
            
            • **Consolidación**: El precio tiende a consolidarse dentro de la zona verde (entre mín y máx GEX).
            
            • **Imanes de precio**: Los picos de OI actúan como imanes de precio o barreras intradía.
            
            • **Presión direccional**: 
              - Si el spot está cerca del máx GEX → posible presión alcista
              - Si el spot está cerca del mín GEX → posible presión bajista
            
            • **Movimiento rápido**: Fuera de la zona GEX se incrementa la probabilidad de movimiento rápido (despinning).
            
            **🎯 Estrategias Específicas:**
            
            • **Bull Put Spreads**: Ubícalos justo debajo de la zona verde si el spot está subiendo.
            
            • **Bear Call Spreads**: Ubícalos justo arriba de la zona verde si el spot está cayendo.
            
            • **Iron Condor**: Ideal si el spot está bien centrado dentro de la zona GEX y el mercado está quieto.
            """
            
            st.markdown(recomendaciones)

            # === TABLA DE DATOS ===
            st.subheader("📊 Datos Filtrados")
            
            # Mostrar tabla con datos clave
            display_df = df_filtered[['StrikePrice', 'net_gex', 'total_oi', 'CallOpenInt', 'PutOpenInt']].copy()
            display_df = display_df.round(2)
            display_df.columns = ['Strike', 'Net GEX', 'Total OI', 'Call OI', 'Put OI']
            
            st.dataframe(display_df, use_container_width=True)

    except Exception as e:
        st.error(f"Error durante el análisis: {str(e)}")
        st.info("Verifique que el ticker sea válido y que los datos estén disponibles en CBOE.")

else:
    st.info("👈 Configure los parámetros en la barra lateral y presione 'Ejecutar Análisis' para comenzar.")
    
    # Información adicional
    st.markdown("""
    ## 📖 Información sobre la Aplicación
    
    Esta aplicación analiza el **Gamma Exposure (GEX)** de opciones usando datos en tiempo real de CBOE.
    
    ### 🎯 Características principales:
    - **Gamma Exposure Total**: Análisis del impacto del gamma en el precio del subyacente
    - **Open Interest**: Visualización de la concentración de contratos abiertos
    - **Perfil de Gamma**: Análisis del comportamiento del gamma a diferentes niveles de precio
    - **Zonas clave**: Identificación de niveles críticos de soporte y resistencia
    - **Recomendaciones**: Estrategias específicas para trading de opciones 0DTE
    
    ### 📊 Tickers disponibles:
    - **SPX**: S&P 500 Index
    - **VIX**: Volatility Index
    - **RUT**: Russell 2000 Index
    - Y otros índices disponibles en CBOE
    
    ### ⚙️ Parámetros:
    - **Ticker**: Símbolo del activo a analizar
    - **Width**: Rango de strikes alrededor del precio spot (en puntos)
    """)
