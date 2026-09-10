"""
Daily Theme Stats Chart Generator
=================================

This script generates an interactive HTML dashboard (charts.html) from the
daily statistics files produced by the NewsFeed application.

Data Source:
The script looks for 'daily_[theme].txt' files, which are typically created
in the 'stats/' directory of this project.

How to use:
1. From the project root, simply run:
   python utils/generate_charts.py
2. The script will automatically scan the 'stats/' folder and generate a 'charts.html' file.
3. Open 'charts.html' in your browser to view the interactive charts.

Note: No external dependencies are required. Uses standard libraries and Chart.js via CDN.
"""

import os
import glob
import json
import yaml

def load_config(config_path="config/config.yaml"):
    if not os.path.exists(config_path):
        return None
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def compute_rolling_avg(values, window=7):
    return [
        round(sum(values[max(0, i - window + 1):i + 1]) / len(values[max(0, i - window + 1):i + 1]), 1)
        for i in range(len(values))
    ]

def parse_file(filepath):
    data = {'dates': [], 'seen': [], 'pub': [], 'rate': []}
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        # Skip the header (first 2 lines)
        for line in lines[2:]:
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                date = parts[0]
                seen = int(parts[1])
                pub = int(parts[2])
                rate = float(parts[3].replace('%', '').strip())
                data['dates'].append(date)
                data['seen'].append(seen)
                data['pub'].append(pub)
                data['rate'].append(rate)
    data['seen_avg'] = compute_rolling_avg(data['seen'])
    data['pub_avg'] = compute_rolling_avg(data['pub'])
    data['rate_avg'] = compute_rolling_avg(data['rate'])
    return data

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    config = load_config(os.path.join(project_root, 'config/config.yaml'))
    
    stats_dir_name = config.get('stats_folder', 'stats') if config else 'stats'
    stats_dir = os.path.join(project_root, stats_dir_name)
    
    # Priority 1: Check in configured 'stats' subdirectory
    files = glob.glob(os.path.join(stats_dir, 'daily_*.txt'))

    # Priority 2: Check in current directory (if run from inside stats/ or if files moved)
    if not files:
        files = glob.glob(os.path.join(project_root, 'daily_*.txt'))
        if files:
            stats_dir = project_root

    if not files:
        print(f"Error: No daily theme files (daily_*.txt) found in {stats_dir} or {project_root}.")
        return

    themes_data = {}
    for filepath in files:
        filename = os.path.basename(filepath)
        theme = filename.replace('daily_', '').replace('.txt', '')
        themes_data[theme] = parse_file(filepath)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Theme Stats Charts</title>
    <!-- Using Chart.js via CDN, requiring no local package installation -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .toggle-container {{
            display: inline-flex;
            background-color: #e0e0e0;
            border-radius: 24px;
            padding: 4px;
            margin-top: 15px;
            box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
        }}
        .toggle-btn {{
            border: none;
            background: none;
            padding: 8px 18px;
            font-size: 14px;
            font-weight: 500;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.2s ease;
            color: #555;
        }}
        .toggle-btn.active {{
            background-color: #ffffff;
            color: #1a73e8;
            box-shadow: 0 2px 4px rgba(0,0,0,0.15);
            font-weight: 600;
        }}
        .toggle-btn:hover:not(.active) {{
            color: #111;
        }}
        .charts-container {{
            display: flex;
            flex-direction: column;
            gap: 30px;
            align-items: center;
        }}
        .chart-card {{
            width: 90%;
            max-width: 1000px;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .chart-title {{
            text-align: center;
            text-transform: capitalize;
            color: #333;
            margin-top: 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Daily Theme Statistics</h1>
        <p>Evolution of articles seen, published, and publish rate.</p>
        <div class="toggle-container">
            <button class="toggle-btn active" data-view="daily" onclick="switchView('daily')">Daily Stats</button>
            <button class="toggle-btn" data-view="rolling" onclick="switchView('rolling')">7-Day Rolling Average</button>
            <button class="toggle-btn" data-view="both" onclick="switchView('both')">Both</button>
        </div>
    </div>

    <div class="charts-container" id="charts"></div>

    <script>
        const themesData = {json.dumps(themes_data)};
        const chartsDiv = document.getElementById('charts');
        const charts = [];

        function switchView(view) {{
            document.querySelectorAll('.toggle-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.view === view);
            }});

            const showDaily = (view === 'daily' || view === 'both');
            const showRolling = (view === 'rolling' || view === 'both');

            charts.forEach(chart => {{
                chart.setDatasetVisibility(0, showDaily);
                chart.setDatasetVisibility(1, showDaily);
                chart.setDatasetVisibility(2, showDaily);
                chart.setDatasetVisibility(3, showRolling);
                chart.setDatasetVisibility(4, showRolling);
                chart.setDatasetVisibility(5, showRolling);
                chart.update();
            }});
        }}

        for (const [theme, data] of Object.entries(themesData)) {{
            const themeCard = document.createElement('div');
            themeCard.className = 'chart-card';

            const title = document.createElement('h2');
            title.className = 'chart-title';
            title.textContent = theme.replace(/_/g, ' ');
            themeCard.appendChild(title);

            const canvasContainer = document.createElement('div');
            canvasContainer.style.position = 'relative';
            canvasContainer.style.height = '400px';
            canvasContainer.style.width = '100%';

            const canvas = document.createElement('canvas');
            canvasContainer.appendChild(canvas);
            themeCard.appendChild(canvasContainer);
            chartsDiv.appendChild(themeCard);

            const chart = new Chart(canvas, {{
                type: 'line',
                data: {{
                    labels: data.dates,
                    datasets: [
                        {{
                            label: 'Articles Seen',
                            data: data.seen,
                            borderColor: 'rgb(54, 162, 235)',
                            backgroundColor: 'rgba(54, 162, 235, 0.1)',
                            yAxisID: 'y',
                            tension: 0.3,
                            fill: false
                        }},
                        {{
                            label: 'Articles Published',
                            data: data.pub,
                            borderColor: 'rgb(75, 192, 192)',
                            backgroundColor: 'rgba(75, 192, 192, 0.1)',
                            yAxisID: 'y',
                            tension: 0.3,
                            fill: false
                        }},
                        {{
                            label: 'Publish Rate (%)',
                            data: data.rate,
                            borderColor: 'rgb(255, 99, 132)',
                            backgroundColor: 'rgba(255, 99, 132, 0.1)',
                            yAxisID: 'y1',
                            tension: 0.3,
                            fill: false
                        }},
                        {{
                            label: 'Seen (7d Avg)',
                            data: data.seen_avg,
                            borderColor: 'rgb(26, 115, 232)',
                            backgroundColor: 'rgba(26, 115, 232, 0.1)',
                            borderDash: [5, 5],
                            yAxisID: 'y',
                            tension: 0.3,
                            fill: false,
                            hidden: true
                        }},
                        {{
                            label: 'Published (7d Avg)',
                            data: data.pub_avg,
                            borderColor: 'rgb(0, 150, 136)',
                            backgroundColor: 'rgba(0, 150, 136, 0.1)',
                            borderDash: [5, 5],
                            yAxisID: 'y',
                            tension: 0.3,
                            fill: false,
                            hidden: true
                        }},
                        {{
                            label: 'Publish Rate (7d Avg %)',
                            data: data.rate_avg,
                            borderColor: 'rgb(216, 27, 96)',
                            backgroundColor: 'rgba(216, 27, 96, 0.1)',
                            borderDash: [5, 5],
                            yAxisID: 'y1',
                            tension: 0.3,
                            fill: false,
                            hidden: true
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false,
                    }},
                    plugins: {{
                        legend: {{
                            onClick: function(e, legendItem, legend) {{
                                const index = legendItem.datasetIndex;
                                const isVisible = legend.chart.isDatasetVisible(index);
                                charts.forEach(c => {{
                                    c.setDatasetVisibility(index, !isVisible);
                                    c.update();
                                }});
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    let label = context.dataset.label || '';
                                    if (label) {{
                                        label += ': ';
                                    }}
                                    if (context.parsed.y !== null) {{
                                        label += context.parsed.y;
                                        if (context.dataset.yAxisID === 'y1') {{
                                            label += '%';
                                        }}
                                    }}
                                    return label;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            display: true,
                            title: {{
                                display: true,
                                text: 'Date'
                            }}
                        }},
                        y: {{
                            type: 'linear',
                            display: true,
                            position: 'left',
                            title: {{
                                display: true,
                                text: 'Articles Count'
                            }}
                        }},
                        y1: {{
                            type: 'linear',
                            display: true,
                            position: 'right',
                            beginAtZero: true,
                            min: 0,
                            title: {{
                                display: true,
                                text: 'Publish Rate (%)'
                            }},
                            grid: {{
                                drawOnChartArea: false
                            }}
                        }}
                    }}
                }}
            }});
            charts.push(chart);
        }}
    </script>
</body>
</html>
"""
    output_path = os.path.join(project_root, 'charts.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Charts successfully generated. Open {output_path} in your browser to view.")

if __name__ == "__main__":
    main()
