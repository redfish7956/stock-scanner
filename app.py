with tab_chart:
                import json
                import streamlit.components.v1 as components

                chart_df = df[df['代號'] == sel_code].sort_values('日期', ascending=True).copy()
                
                if not chart_df.empty:
                    # 計算均線
                    chart_df['MA5'] = chart_df['收盤價'].rolling(window=5).mean()
                    chart_df['MA10'] = chart_df['收盤價'].rolling(window=10).mean()
                    chart_df['MA20'] = chart_df['收盤價'].rolling(window=20).mean()
                    chart_df['MA60'] = chart_df['收盤價'].rolling(window=60).mean()
                    
                    # 轉換日期格式符合 TradingView 需求 (YYYY-MM-DD)
                    chart_df['DateStr'] = chart_df['日期'].dt.strftime('%Y-%m-%d')

                    # 1. 準備 K 線資料
                    candle_data = chart_df[['DateStr', '開盤價', '最高價', '最低價', '收盤價']].rename(
                        columns={'DateStr':'time', '開盤價':'open', '最高價':'high', '最低價':'low', '收盤價':'close'}
                    ).to_dict(orient='records')

                    # 2. 準備成交量資料 (上漲紅，下跌綠)
                    vol_data = []
                    for _, row in chart_df.iterrows():
                        color = 'rgba(255, 51, 51, 0.6)' if row['收盤價'] >= row['開盤價'] else 'rgba(0, 170, 0, 0.6)'
                        vol_data.append({'time': row['DateStr'], 'value': row['成交量(張)'], 'color': color})

                    # 3. 準備均線資料 (需排除 NaN 避免圖表報錯)
                    def get_ma_data(col_name):
                        return chart_df.dropna(subset=[col_name])[['DateStr', col_name]].rename(
                            columns={'DateStr':'time', col_name:'value'}
                        ).to_dict(orient='records')

                    js_candle = json.dumps(candle_data)
                    js_vol = json.dumps(vol_data)
                    js_ma5 = json.dumps(get_ma_data('MA5'))
                    js_ma10 = json.dumps(get_ma_data('MA10'))
                    js_ma20 = json.dumps(get_ma_data('MA20'))
                    js_ma60 = json.dumps(get_ma_data('MA60'))

                    # 建立 TradingView HTML 模板與腳本
                    html_content = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
                        <style>
                            body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fff; }}
                            .toolbar {{ display: flex; gap: 8px; padding: 12px; background: #f8f9fa; border-bottom: 1px solid #e0e0e0; align-items: center; }}
                            .toolbar-label {{ font-size: 14px; font-weight: 600; color: #333; margin-right: 4px; }}
                            .btn {{ padding: 6px 12px; cursor: pointer; border: 1px solid #d1d5db; background: #fff; border-radius: 6px; font-size: 13px; color: #374151; transition: all 0.2s; }}
                            .btn:hover {{ background: #f3f4f6; border-color: #9ca3af; }}
                            .btn:active {{ background: #e5e7eb; }}
                            #tvchart {{ width: 100%; height: 520px; }}
                        </style>
                    </head>
                    <body>
                        <div class="toolbar">
                            <span class="toolbar-label">快速縮放：</span>
                            <button class="btn" onclick="setRange(5)">近 5 日</button>
                            <button class="btn" onclick="setRange(20)">近 20 日</button>
                            <button class="btn" onclick="setRange(60)">近一季</button>
                            <button class="btn" onclick="setRange(120)">近半年</button>
                            <button class="btn" onclick="setRange(9999)">全部顯示</button>
                        </div>
                        <div id="tvchart"></div>
                        <script>
                            // 初始化圖表
                            const chart = LightweightCharts.createChart(document.getElementById('tvchart'), {{
                                layout: {{ textColor: '#333', background: {{ type: 'solid', color: '#ffffff' }} }},
                                crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
                                rightPriceScale: {{ scaleMargins: {{ top: 0.1, bottom: 0.25 }}, borderVisible: false }},
                                timeScale: {{ borderVisible: false, timeVisible: true, fixLeftEdge: true }},
                                grid: {{ vertLines: {{ color: '#f0f3fa' }}, horzLines: {{ color: '#f0f3fa' }} }}
                            }});

                            // 響應式：隨瀏覽器改變大小自動重新計算比例
                            new ResizeObserver(entries => {{
                                if (entries.length === 0 || entries[0].target !== document.getElementById('tvchart')) return;
                                const newRect = entries[0].contentRect;
                                chart.applyOptions({{ width: newRect.width, height: newRect.height }});
                            }}).observe(document.getElementById('tvchart'));

                            // 設定 K 線
                            const candleSeries = chart.addCandlestickSeries({{
                                upColor: '#FF3333', downColor: '#00AA00', borderVisible: false,
                                wickUpColor: '#FF3333', wickDownColor: '#00AA00'
                            }});
                            candleSeries.setData({js_candle});

                            // 設定成交量 (作為背景疊加在最下方 20% 區域)
                            const volumeSeries = chart.addHistogramSeries({{
                                priceFormat: {{ type: 'volume' }},
                                priceScaleId: '', // 獨立 Y 軸
                            }});
                            volumeSeries.priceScale().applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
                            volumeSeries.setData({js_vol});

                            // 設定均線 (crosshairMarkerVisible: false 讓游標比較乾淨)
                            const ma5Series = chart.addLineSeries({{ color: 'orange', lineWidth: 2, title: '5MA', crosshairMarkerVisible: false }});
                            ma5Series.setData({js_ma5});
                            
                            const ma10Series = chart.addLineSeries({{ color: 'blue', lineWidth: 2, title: '10MA', crosshairMarkerVisible: false }});
                            ma10Series.setData({js_ma10});
                            
                            const ma20Series = chart.addLineSeries({{ color: 'purple', lineWidth: 2, title: '20MA', crosshairMarkerVisible: false }});
                            ma20Series.setData({js_ma20});
                            
                            const ma60Series = chart.addLineSeries({{ color: 'green', lineWidth: 2, title: '60MA', crosshairMarkerVisible: false }});
                            ma60Series.setData({js_ma60});

                            // 區間切換核心邏輯
                            function setRange(days) {{
                                const dataLength = {len(chart_df)};
                                const fromIndex = Math.max(0, dataLength - days);
                                const toIndex = dataLength - 1;
                                // 呼叫 setVisibleLogicalRange，Y軸就會根據此區間自動調整最佳比例！
                                chart.timeScale().setVisibleLogicalRange({{ from: fromIndex, to: toIndex }});
                            }}

                            // 載入時預設先縮放到「近一季 (60日)」的畫面
                            setTimeout(() => setRange(60), 50);
                        </script>
                    </body>
                    </html>
                    """
                    
                    # 透過 Streamlit 渲染 HTML 組件
                    components.html(html_content, height=600)
                else:
                    st.warning("無歷史資料可繪製 K 線圖。")
