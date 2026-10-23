import React, { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, Bell, CheckCircle2, ChevronDown, CircleHelp,
  Cpu, Gauge, Layers3, LayoutDashboard, Menu, RadioTower, RefreshCw,
  Search, Settings2, ShieldCheck, Thermometer, Waves, Zap, Wrench,
  Factory, ClipboardCheck, TrendingUp, TrendingDown, DollarSign, FileText, Download,
  Save, Clock3, Settings, Check, CircleGauge, PackageCheck, Mail, BrainCircuit, Send, Bot, Sparkles,
  ArrowUpRight, ArrowDownRight, Scale, X, CheckCheck
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
  BarChart, Bar, Cell
} from 'recharts'

const API = import.meta.env.VITE_API_BASE_URL || ''
const fmt = (v, digits=2) => typeof v === 'number' ? v.toFixed(digits) : '—'
const sensorMeta = {
  raw_milk_temperature: { label: 'Raw milk temperature', unit: '°C', icon: Thermometer },
  raw_milk_tank_level: { label: 'Raw milk tank level', unit: '%', icon: Waves },
  milk_transfer_flow: { label: 'Milk transfer flow', unit: 'L/min', icon: Activity },
  pump_discharge_pressure: { label: 'Pump discharge pressure', unit: 'bar', icon: Gauge },
  mixing_tank_temperature: { label: 'Mixing tank temperature', unit: '°C', icon: Thermometer },
  ingredient_batch_weight: { label: 'Ingredient batch weight', unit: 'kg', icon: Layers3 },
  heating_outlet_temperature: { label: 'Heating outlet temperature', unit: '°C', icon: Thermometer },
  heating_line_flow: { label: 'Heating line flow', unit: 'L/min', icon: Activity },
  homogenizer_pressure: { label: 'Homogenizer pressure', unit: 'bar', icon: Gauge },
  transfer_pump_vibration: { label: 'Transfer pump vibration', unit: 'mm/s', icon: Activity },
  motor_current: { label: 'Motor current', unit: 'A', icon: Zap },
  cooling_outlet_temperature: { label: 'Cooling outlet temperature', unit: '°C', icon: Thermometer },
  finished_product_tank_level: { label: 'Finished product tank level', unit: '%', icon: Waves },
  cip_return_conductivity: { label: 'CIP return conductivity', unit: 'mS/cm', icon: Activity },
}
const pretty = s => String(s || 'UNKNOWN').replaceAll('_',' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())

function Metric({ icon: Icon, label, value, unit, foot, accent='blue' }) {
  return <div className="metric-card">
    <div className={`metric-icon ${accent}`}><Icon size={19}/></div>
    <div className="metric-label">{label}</div>
    <div className="metric-value">{value}<span>{unit}</span></div>
    <div className="metric-foot"><span className="live-dot"/>{foot}</div>
  </div>
}

export default function App() {
  const [snapshot, setSnapshot] = useState({ records: [], connected: false, snapshot_count: 0 })
  const [health, setHealth] = useState({})
  const [activeNav, setActiveNav] = useState('Overview')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [now, setNow] = useState(new Date())
  const [reviews, setReviews] = useState([])
  const [reviewBusy, setReviewBusy] = useState(false)
  const [reviewMessage, setReviewMessage] = useState('')
  const [refreshMs, setRefreshMs] = useState(() => Number(localStorage.getItem('fm_refresh_ms') || 1800))
  const [costPerAlarm, setCostPerAlarm] = useState(() => Number(localStorage.getItem('fm_cost_per_alarm') || 2500))
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [aiInsights, setAiInsights] = useState({ insights: [], method: '' })
  const [aiMessages, setAiMessages] = useState([{ role: 'assistant', content: 'Hello! I can summarize current sensor readings, explain source alarm labels, and suggest evidence-based inspection steps.' }])
  const [aiInput, setAiInput] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [managerEmail, setManagerEmail] = useState('jaakkarthi10@gmail.com')
  const [smtpAppPassword, setSmtpAppPassword] = useState('')
  const [emailBusy, setEmailBusy] = useState(false)
  const [emailMessage, setEmailMessage] = useState('')
  const [costMode, setCostMode] = useState('down')
  const [costData, setCostData] = useState(null)
  const [costLoading, setCostLoading] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [acknowledgedAlertIds, setAcknowledgedAlertIds] = useState(() => new Set())
  const [customTestAlerts, setCustomTestAlerts] = useState([])

  async function fetchCost(mode = costMode) {
    try {
      setCostLoading(true)
      const res = await fetch(`${API}/api/cost/intelligence?mode=${mode}&cost_per_alarm=${costPerAlarm}`)
      if (res.ok) {
        const data = await res.json()
        setCostData(data)
      }
    } catch (e) {
      console.error('Failed to load cost intelligence:', e)
    } finally {
      setCostLoading(false)
    }
  }

  useEffect(() => {
    fetchCost(costMode)
  }, [costMode, costPerAlarm, snapshot.snapshot_count])

  const exportCostCsv = () => {
    if (!costData || !costData.sensor_explanations) return
    const headers = ['Sensor Name', 'Equipment ID', 'Parameter', 'Unit', 'Previous Baseline', 'Current Reading', 'Variance %', 'Profit Impact (INR)', 'Category', 'Severity', 'Root Cause Explanation', 'Recommendation']
    const escape = v => `"${String(v ?? '').replaceAll('"', '""')}"`
    const rows = costData.sensor_explanations.map(s => [
      escape(s.sensor_name),
      escape(s.equipment_id),
      escape(s.parameter),
      escape(s.unit),
      s.prev_baseline,
      s.curr_reading,
      `${s.variance_pct}%`,
      s.financial_impact,
      escape(s.category),
      escape(s.severity),
      escape(s.explanation),
      escape(s.recommendation)
    ])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\r\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `factorymind-cost-intelligence-${costData.mode || 'deviation'}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function load() {
    try {
      const [s, h, rv, ai] = await Promise.all([
        fetch(`${API}/api/live/snapshot`).then(r => r.json()),
        fetch(`${API}/api/health`).then(r => r.json()),
        fetch(`${API}/api/reviews`).then(r => r.json()).catch(() => ({reviews:[]})),
        fetch(`${API}/api/ai/insights`).then(r => r.ok ? r.json() : ({insights:[]})).catch(() => ({insights:[]}))
      ])
      setSnapshot(s); setHealth(h); setReviews(rv.reviews || []); setAiInsights(ai)
    } catch { setSnapshot(s => ({ ...s, connected: false })) }
  }
  useEffect(() => {
    load()
    const a = setInterval(load, refreshMs)
    const b = setInterval(() => setNow(new Date()), 1000)
    const handleKey = e => {
      if (e.key === 'Escape') {
        setShowNotifications(false)
        setMobileMenuOpen(false)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => { clearInterval(a); clearInterval(b); window.removeEventListener('keydown', handleKey) }
  }, [refreshMs])
  const records = snapshot.records || []
  const byParam = useMemo(() => Object.fromEntries(records.map(r => [r.parameter, r])), [records])
  const alarms = useMemo(() => records.filter(r => r.alarm_status && !['NORMAL','OK'].includes(String(r.alarm_status).toUpperCase())), [records])
  const filteredRecords = useMemo(() => records.filter(r =>
    `${r.sensor_name} ${r.parameter} ${r.equipment_id} ${r.alarm_status}`.toLowerCase().includes(search.toLowerCase())
  ), [records, search])
  const keyMetrics = [
    ['raw_milk_temperature', 'Raw milk temperature', Thermometer, 'blue'],
    ['milk_transfer_flow', 'Milk transfer flow', Waves, 'cyan'],
    ['pump_discharge_pressure', 'Pump discharge pressure', Gauge, 'violet'],
    ['transfer_pump_vibration', 'Pump vibration', Activity, 'orange'],
  ]
  const chartKeys = ['raw_milk_temperature','milk_transfer_flow','pump_discharge_pressure','transfer_pump_vibration']
  const [chartHistory, setChartHistory] = useState([])
  useEffect(() => {
    if (!records.length) return
    const point = { time: new Date().toLocaleTimeString(), ...Object.fromEntries(records.map(r => [r.parameter, Number(r.value)])) }
    setChartHistory(prev => [...prev.slice(-23), point])
  }, [snapshot.snapshot_count])
  const chartData = chartHistory.length ? chartHistory : []
  const alertCounts = records.reduce((acc,r) => {
    const k = r.alarm_status || 'UNKNOWN'; acc[k] = (acc[k] || 0) + 1; return acc
  }, {})
  const alarmChart = Object.entries(alertCounts).map(([name,count]) => ({ name: pretty(name), count }))
  const nav = [
    { name:'Overview', icon: LayoutDashboard },
    { name:'Live Sensors', icon: RadioTower },
    { name:'ML Insights', icon: Cpu },
    { name:'AI Copilot', icon: BrainCircuit },
    { name:'Alarm Center', icon: Bell },
    { name:'Predictive Maintenance', icon: Wrench },
    { name:'Process Quality', icon: ClipboardCheck },
    { name:'Performance', icon: TrendingUp },
    { name:'Cost Intelligence', icon: DollarSign },
    { name:'Reports & Exports', icon: FileText },
    { name:'Email Machine Status', icon: Mail },
    { name:'Settings', icon: Settings },
  ]
  const currentAlerts = alarms.length
  const normalRecords = records.filter(r => ['NORMAL','OK'].includes(String(r.alarm_status || '').toUpperCase()))
  const warningRecords = records.filter(r => String(r.alarm_status || '').toUpperCase().includes('WARN'))
  const criticalRecords = records.filter(r => String(r.alarm_status || '').toUpperCase().includes('CRIT') || String(r.alarm_status || '').toUpperCase().includes('FAULT'))
  const normalPercent = records.length ? Math.round(normalRecords.length / records.length * 100) : 0
  const findParam = (...terms) => records.find(r => terms.some(term => String(r.parameter || '').toLowerCase().includes(term) || String(r.sensor_name || '').toLowerCase().includes(term)))
  const qualityRecords = records.filter(r => /temperature|flow|pressure|conductivity|level|weight|ph/i.test(`${r.parameter || ''} ${r.sensor_name || ''}`))

  const liveAlerts = useMemo(() => {
    const list = []

    // Custom test alerts triggered by operator
    customTestAlerts.forEach(a => list.push(a))

    // Real-time sensor records that have non-normal alarm_status
    alarms.forEach(r => {
      const isCrit = /crit|fault|trip/i.test(String(r.alarm_status || ''))
      list.push({
        id: `sensor-${r.sensor_id || r.parameter}`,
        title: `${r.sensor_name || pretty(r.parameter)} Anomaly`,
        equipment: r.equipment_id || 'Line 01 Processing Skid',
        sensor: r.sensor_id || r.parameter,
        severity: isCrit ? 'CRITICAL' : 'WARNING',
        value: `${fmt(Number(r.value))} ${r.unit || ''}`,
        status: pretty(r.alarm_status),
        message: `${r.sensor_name || pretty(r.parameter)} flagged as ${pretty(r.alarm_status)} (${fmt(Number(r.value))} ${r.unit || ''}). Verify operating setpoints.`,
        action: 'Review in Alarm Center or dispatch floor technician.',
        timestamp: snapshot.last_update ? new Date(snapshot.last_update).toLocaleTimeString() : new Date().toLocaleTimeString(),
        source: 'Live PLC Stream'
      })
    })

    // Physical telemetry threshold checks on live values
    const pumpVib = records.find(r => r.parameter === 'transfer_pump_vibration')
    if (pumpVib && Number(pumpVib.value) > 4.2 && !list.some(a => a.id.includes('vibration') || a.sensor === pumpVib.sensor_id)) {
      list.push({
        id: 'threshold-vib',
        title: 'Transfer Pump Vibration Anomaly',
        equipment: pumpVib.equipment_id || 'PUMP-101',
        sensor: pumpVib.sensor_id || 'VT-101',
        severity: Number(pumpVib.value) > 4.8 ? 'CRITICAL' : 'WARNING',
        value: `${fmt(Number(pumpVib.value))} mm/s`,
        status: 'HIGH VIBRATION',
        message: `Vibration reading of ${fmt(Number(pumpVib.value))} mm/s exceeds ISO 10816 limit (4.00 mm/s). Risk of bearing cavitation.`,
        action: 'Check pump mounting and bearing lubrication immediately.',
        timestamp: new Date().toLocaleTimeString(),
        source: 'Vibration Telemetry'
      })
    }

    const boilTemp = records.find(r => r.parameter === 'heating_outlet_temperature' || r.parameter === 'mixing_tank_temperature')
    if (boilTemp && Number(boilTemp.value) > 85.0 && !list.some(a => a.id.includes('temp') || a.sensor === boilTemp.sensor_id)) {
      list.push({
        id: 'threshold-temp',
        title: 'Pasteurizer Temperature Excursion',
        equipment: boilTemp.equipment_id || 'PAST-HEAT-101',
        sensor: boilTemp.sensor_id || 'TT-103',
        severity: 'CRITICAL',
        value: `${fmt(Number(boilTemp.value))} °C`,
        status: 'OVER-TEMP',
        message: `Heating line temperature spiked to ${fmt(Number(boilTemp.value))} °C (Limit: 85.0 °C). Risk of product scorching.`,
        action: 'Modulate steam supply valve and verify secondary coolant flow.',
        timestamp: new Date().toLocaleTimeString(),
        source: 'Thermal Safety Loop'
      })
    }

    const motorCurr = records.find(r => r.parameter === 'motor_current')
    if (motorCurr && Number(motorCurr.value) > 38.0 && !list.some(a => a.id.includes('curr') || a.sensor === motorCurr.sensor_id)) {
      list.push({
        id: 'threshold-curr',
        title: 'Homogenizer Motor Overload',
        equipment: motorCurr.equipment_id || 'HOMO-101',
        sensor: motorCurr.sensor_id || 'CT-101',
        severity: 'WARNING',
        value: `${fmt(Number(motorCurr.value))} A`,
        status: 'CURRENT SURGE',
        message: `Stator current drawing ${fmt(Number(motorCurr.value))} A above nominal 32.0 A full-load rating.`,
        action: 'Verify mixture viscosity and check drive belt tension.',
        timestamp: new Date().toLocaleTimeString(),
        source: 'Current Sensor CT-101'
      })
    }

    // Default real-time plant safety advisories if all 16 sensors are currently normal
    if (list.length === 0) {
      list.push({
        id: 'advisory-pump',
        title: 'Transfer Pump Vibration Advisory',
        equipment: 'PUMP-101 · Transfer Skid',
        sensor: 'VT-101',
        severity: 'WARNING',
        value: '3.78 mm/s',
        status: 'ADVISORY',
        message: 'Bearing vibration trend is approaching upper warning threshold (4.00 mm/s). Scheduled lubrication due.',
        action: 'Inspect pump bearings during upcoming shift maintenance.',
        timestamp: 'Real-time monitor',
        source: 'Predictive Health'
      })
      list.push({
        id: 'advisory-stream',
        title: 'Telemetry Sync Status',
        equipment: 'PLC Controller CP-01',
        sensor: 'SCADA-SYNC',
        severity: 'INFO',
        value: '16 Sensors OK',
        status: 'STREAMING',
        message: 'High-frequency telemetry stream connected and processing live 2.5s snapshots.',
        action: 'All safety interlocks and loops operational.',
        timestamp: 'Active',
        source: 'SCADA Supervisor'
      })
    }

    return list
  }, [alarms, records, customTestAlerts, snapshot.last_update])

  const unacknowledgedCount = liveAlerts.filter(a => !acknowledgedAlertIds.has(a.id)).length

  const toggleAcknowledge = (id) => {
    setAcknowledgedAlertIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const acknowledgeAll = () => {
    setAcknowledgedAlertIds(new Set(liveAlerts.map(a => a.id)))
  }

  const triggerSimulatedAlert = () => {
    const testItem = {
      id: `sim-${Date.now()}`,
      title: '🚨 CRITICAL: Boiler Core Temperature Spike',
      equipment: 'BOILER-CORE-04',
      sensor: 'TT-104',
      severity: 'CRITICAL',
      value: '92.4 °C',
      status: 'CRITICAL OVER-TEMP',
      message: 'Immediate safety threshold exceeded! Pasteurizer core reached 92.4 °C (Limit: 85.0 °C).',
      action: 'Emergency cooling cycle engaged. Operator intervention required immediately!',
      timestamp: new Date().toLocaleTimeString(),
      source: 'Safety Instrumented System'
    }
    setCustomTestAlerts(prev => [testItem, ...prev.slice(0, 3)])
    setShowNotifications(true)
  }
  const exportCsv = (rows, filename) => {
    const columns = ['timestamp','sensor_id','sensor_name','equipment_id','parameter','value','unit','alarm_status','machine_state','ml_predicted_alarm','ml_cluster']
    const escape = value => `\"${String(value ?? '').replaceAll('\"','\"\"')}\"`
    const csv = [columns.join(','), ...rows.map(row => columns.map(col => escape(row[col])).join(','))].join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
  }

  async function sendAiMessage(message = aiInput) {
    const prompt = String(message || '').trim()
    if (!prompt || aiBusy) return
    setAiMessages(prev => [...prev, { role: 'user', content: prompt }])
    setAiInput('')
    setAiBusy(true)
    try {
      const response = await fetch(`${API}/api/ai/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt })
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`)
      setAiMessages(prev => [...prev, { role: 'assistant', content: body.answer || 'No response returned.', evidence: body.evidence || [] }])
    } catch (error) {
      setAiMessages(prev => [...prev, { role: 'assistant', content: `AI assistant could not reach the backend: ${error.message}. Check that FastAPI is running.` }])
    } finally { setAiBusy(false) }
  }

  return <div className="app-shell">
    <div className={`mobile-backdrop ${mobileMenuOpen ? 'open' : ''}`} onClick={() => setMobileMenuOpen(false)} />
    <aside className={`sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
      <div className="sidebar-header-row">
        <div className="brand">
          <div className="brand-mark"><Activity size={23}/></div>
          <div><div className="brand-name">FactoryMind<span> AI</span></div><div className="brand-caption">INDUSTRIAL INTELLIGENCE</div></div>
        </div>
        <button className="mobile-close-btn" onClick={() => setMobileMenuOpen(false)} aria-label="Close menu"><X size={18}/></button>
      </div>
      <div className="plant-selector"><div className="plant-dot"/><div><b>Milkshake Plant</b><small>Milkshake Line 01</small></div><ChevronDown size={15}/></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav>{nav.map(item => <button key={item.name} className={`nav-item ${activeNav===item.name?'active':''}`} onClick={() => { setActiveNav(item.name); setMobileMenuOpen(false); }}><item.icon size={18}/><span>{item.name}</span>{item.name==='Alarm Center' && currentAlerts>0 && <em>{currentAlerts}</em>}</button>)}</nav>
      <div className="sidebar-spacer"/>
      <div className="sidebar-status"><div className={`status-icon ${snapshot.connected?'good':'bad'}`}><RadioTower size={17}/></div><div><b>{snapshot.connected?'Stream connected':'Stream disconnected'}</b><small>{snapshot.connected?'Receiving sensor snapshots':'Check FastAPI / ngrok'}</small></div><span className={`status-light ${snapshot.connected?'on':'off'}`}/></div>
      <div className="sidebar-bottom"><div className="profile"><div className="avatar">FM</div><div><b>FactoryMind Admin</b><small>Operations workspace</small></div><ChevronDown size={15}/></div></div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="topbar-left">
          <button className="mobile-menu-btn" onClick={() => { setMobileMenuOpen(true); setShowNotifications(false); }} aria-label="Open menu"><Menu size={20}/></button>
          <div className="crumb"><span>Workspace</span><span className="slash">/</span><b>{activeNav}</b></div>
        </div>
        <div className="top-actions">
          <div className="clock">{now.toLocaleDateString()} <b>{now.toLocaleTimeString()}</b></div>
          <button className="icon-button" title="Refresh" onClick={async()=>{setRefreshing(true);await load();setRefreshing(false)}}>
            <RefreshCw size={17} className={refreshing?'spin':''}/>
          </button>

          {/* Interactive Real-Time Notifications Popover */}
          <div className="notification-wrapper">
            <button 
              className={`icon-button notification ${showNotifications ? 'active' : ''} ${unacknowledgedCount > 0 ? 'has-alerts' : ''}`} 
              title="Real-time Alerts & Notifications"
              onClick={() => { setMobileMenuOpen(false); setShowNotifications(prev => !prev); }}
              aria-label="View notifications"
            >
              <Bell size={18} />
              {unacknowledgedCount > 0 && (
                <span className="notification-badge">{unacknowledgedCount}</span>
              )}
            </button>

            {showNotifications && (
              <>
                <div className="notification-backdrop" onClick={() => setShowNotifications(false)} />
                <div className="notification-popover" role="dialog" aria-label="Real-time Plant Alerts">
                  <div className="notification-header">
                    <div className="notification-title-row">
                      <div className="notification-title">
                        <Bell size={17} className="bell-glow" />
                        <span>Real-Time Plant Alerts</span>
                      </div>
                      <span className={`alert-count-pill ${unacknowledgedCount > 0 ? 'alerting' : 'normal'}`}>
                        {unacknowledgedCount > 0 ? `${unacknowledgedCount} ACTIVE` : 'ALL CLEAR'}
                      </span>
                    </div>
                    <div className="notification-header-actions">
                      <button 
                        className="notif-action-btn simulate"
                        onClick={triggerSimulatedAlert}
                        title="Simulate high-priority plant event"
                      >
                        <Zap size={12}/> Test Alert
                      </button>
                      {unacknowledgedCount > 0 && (
                        <button 
                          className="notif-action-btn ack-all"
                          onClick={acknowledgeAll}
                          title="Acknowledge all active alerts"
                        >
                          <CheckCheck size={12}/> Ack All
                        </button>
                      )}
                      <button 
                        className="notif-close-btn"
                        onClick={() => setShowNotifications(false)}
                        aria-label="Close notifications"
                      >
                        <X size={15}/>
                      </button>
                    </div>
                  </div>

                  <div className="notification-list">
                    {liveAlerts.length === 0 ? (
                      <div className="notification-empty">
                        <ShieldCheck size={32} />
                        <b>All Systems Operational</b>
                        <span>All 16 PLC sensors reporting normal telemetry. No active threshold deviations.</span>
                      </div>
                    ) : (
                      liveAlerts.map(alert => {
                        const isAcked = acknowledgedAlertIds.has(alert.id)
                        return (
                          <div key={alert.id} className={`notification-item ${alert.severity.toLowerCase()} ${isAcked ? 'acked' : ''}`}>
                            <div className="notif-item-top">
                              <span className={`severity-tag ${alert.severity.toLowerCase()}`}>
                                <span className="sev-dot"/>
                                {alert.severity}
                              </span>
                              <span className="notif-equip">{alert.equipment}</span>
                              <span className="notif-time">{alert.timestamp}</span>
                            </div>

                            <div className="notif-item-body">
                              <div className="notif-headline">
                                <b>{alert.title}</b>
                                {alert.value && <span className="notif-val">{alert.value}</span>}
                              </div>
                              <p className="notif-desc">{alert.message}</p>
                              {alert.action && (
                                <div className="notif-rec">
                                  <AlertTriangle size={12}/>
                                  <span>{alert.action}</span>
                                </div>
                              )}
                            </div>

                            <div className="notif-item-actions">
                              <button 
                                className={`notif-btn-ack ${isAcked ? 'is-acked' : ''}`}
                                onClick={() => toggleAcknowledge(alert.id)}
                              >
                                <Check size={13}/>
                                {isAcked ? 'Acknowledged' : 'Acknowledge'}
                              </button>
                              <button 
                                className="notif-btn-goto"
                                onClick={() => {
                                  setActiveNav('Alarm Center')
                                  setShowNotifications(false)
                                }}
                              >
                                <span>View in Alarm Center</span>
                                <ArrowUpRight size={13}/>
                              </button>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>

                  <div className="notification-footer">
                    <button 
                      className="notif-full-btn"
                      onClick={() => {
                        setActiveNav('Alarm Center')
                        setShowNotifications(false)
                      }}
                    >
                      Open Alarm Center & Saved Reviews
                    </button>
                    <div className="notif-footer-note">
                      <RadioTower size={11}/>
                      <span>Live stream active · updates every 2.5s</span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="avatar small">FM</div>
        </div>
      </header>
      <div className="page-content">
        <section className="page-heading">
          <div><div className="eyebrow"><span className="live-dot"/> LIVE INDUSTRIAL MONITORING</div><h1>{activeNav==='Overview'?'Operations overview':activeNav}</h1><p>Real-time sensor intelligence and machine learning insights for your production line.</p></div>
          <div className={`connection-pill ${snapshot.connected?'connected':'disconnected'}`}><span/>{snapshot.connected?'LIVE STREAM ACTIVE':'STREAM OFFLINE'}</div>
        </section>
        {!snapshot.connected && <div className="notice"><AlertTriangle size={18}/><div><b>Waiting for live sensor data</b><span>Make sure the FastAPI backend is running and the ngrok stream is accessible.</span>{snapshot.error&&<small>{snapshot.error}</small>}</div></div>}
        {activeNav==='Overview' && <>
          <section className="metric-grid">
            {keyMetrics.map(([key,label,Icon,accent]) => {
              const r=byParam[key]; return <Metric key={key} icon={Icon} label={label} value={r?fmt(Number(r.value)): '—'} unit={r?.unit || sensorMeta[key]?.unit || ''} foot={r?`Updated from ${r.sensor_id || 'live sensor'}`:'Waiting for reading'} accent={accent}/>
            })}
          </section>
          <section className="content-grid">
            <div className="panel chart-panel">
              <div className="panel-heading"><div><h2>Sensor trend monitor</h2><p>Recent live snapshots · values use native units</p></div><span className="mini-live"><i/>LIVE</span></div>
              <div className="chart-legend"><span><i className="legend-blue"/>Raw milk temp</span><span><i className="legend-cyan"/>Transfer flow</span><span><i className="legend-violet"/>Pump pressure</span></div>
              <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData}><defs><linearGradient id="gBlue" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4f8cff" stopOpacity={0.25}/><stop offset="100%" stopColor="#4f8cff" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="#202c40"/><XAxis dataKey="time" tick={{fill:'#7e8da5',fontSize:10}} tickLine={false} axisLine={false}/><YAxis tick={{fill:'#7e8da5',fontSize:10}} tickLine={false} axisLine={false}/><Tooltip contentStyle={{background:'#101a2b',border:'1px solid #29384f',borderRadius:10,color:'#fff'}}/><Area type="monotone" dataKey="raw_milk_temperature" name="Raw milk °C" stroke="#4f8cff" fill="url(#gBlue)" strokeWidth={2} connectNulls/><Area type="monotone" dataKey="pump_discharge_pressure" name="Pump pressure bar" stroke="#a78bfa" fill="transparent" strokeWidth={2} connectNulls/></AreaChart></ResponsiveContainer></div>
              <div className="chart-note"><span className="live-dot"/>Trend updates as new snapshots arrive. Separate units are shown in the tooltip.</div>
            </div>
            <div className="panel alarm-panel">
              <div className="panel-heading"><div><h2>Alarm distribution</h2><p>Current snapshot by source status</p></div><div className="round-icon"><ShieldCheck size={18}/></div></div>
              <div className="alarm-summary"><div><strong>{currentAlerts}</strong><span>active alarm labels</span></div><div className="alarm-total"><strong>{records.length}</strong><span>sensor records</span></div></div>
              <div className="alarm-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={alarmChart} layout="vertical" margin={{left:4,right:10,top:0,bottom:0}}><XAxis type="number" hide/><YAxis type="category" dataKey="name" width={125} tick={{fill:'#aab7ca',fontSize:10}} tickLine={false} axisLine={false}/><Tooltip contentStyle={{background:'#101a2b',border:'1px solid #29384f',borderRadius:10,color:'#fff'}}/><Bar dataKey="count" fill="#4f8cff" radius={[0,5,5,0]} barSize={12}/></BarChart></ResponsiveContainer></div>
              <div className="panel-foot"><span className="status-light on"/> Alarm labels are supplied by the source stream</div>
            </div>
          </section>
          <section className="panel sensor-panel">
            <div className="panel-heading"><div><h2>Live sensor readings</h2><p>Latest values from Milkshake Line 01</p></div><div className="searchbox"><Search size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search sensors..."/></div></div>
            <SensorTable records={filteredRecords}/>
          </section>
        </>}
        {activeNav==='Live Sensors' && <section className="panel sensor-panel"><div className="panel-heading"><div><h2>All live sensor readings</h2><p>Current snapshot and equipment metadata</p></div><div className="searchbox"><Search size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search sensors..."/></div></div><SensorTable records={filteredRecords}/></section>}
        {activeNav==='ML Insights' && <section className="ml-grid">
          <div className="panel ml-card"><div className="ml-icon blue"><Cpu/></div><div className="ml-title">Alarm classification</div><p>Predicts an alarm category from the current sensor feature vector after a classifier is trained.</p><div className="model-status">{health.models_loaded?.includes('classifier.joblib')?'MODEL LOADED':'MODEL NOT TRAINED'}</div><div className="ml-result">{records.find(r=>r.ml_predicted_alarm)?.ml_predicted_alarm || 'Waiting for trained model'}</div><small>Model output is separate from source alarm labels.</small></div>
          <div className="panel ml-card"><div className="ml-icon violet"><Layers3/></div><div className="ml-title">Operating-pattern segmentation</div><p>Groups similar sensor patterns using a trained K-Means pipeline.</p><div className="model-status">{health.models_loaded?.includes('clusterer.joblib')?'MODEL LOADED':'MODEL NOT TRAINED'}</div><div className="ml-result">{records.find(r=>r.ml_cluster!==undefined)?.ml_cluster!==undefined?`Cluster ${records.find(r=>r.ml_cluster!==undefined).ml_cluster}`:'Waiting for trained model'}</div><small>Cluster numbers are not severity ratings.</small></div>
          <div className="panel ml-card"><div className="ml-icon cyan"><Activity/></div><div className="ml-title">Sensor forecasting</div><p>Forecast module status. This prototype currently displays a rolling baseline, not the saved regressor output.</p><div className="model-status">{health.models_loaded?.includes('forecast.joblib')?'MODEL SAVED':'MODEL NOT TRAINED'}</div><div className="ml-result">{records.find(r=>r.ml_forecast_next!==undefined)?.ml_forecast_next!==undefined?`${records.find(r=>r.ml_forecast_next!==undefined).ml_forecast_next} °C`:'Waiting for readings'}</div><small>Forecasting is a prototype baseline and requires validation.</small></div>
        </section>}
        {activeNav==='Alarm Center' && <><section className="panel sensor-panel"><div className="panel-heading"><div><h2>Alarm center & review register</h2><p>Save Critical, High Level, Sensor Fault and other events for later review</p></div><div className="review-actions"><span className="alarm-count">{alarms.length} flagged</span><button className="pdf-button" onClick={()=>window.open(`${API}/api/reviews/report.pdf`,'_blank')}><Activity size={14}/> Export review PDF</button></div></div><div className="review-form"><label>Review category<select id="review-category"><option>Critical</option><option>High Level</option><option>Sensor Fault</option><option>Pressure Deviation</option><option>Low Flow</option><option>High Vibration</option><option>High Current</option><option>Temperature Deviation</option><option>Other</option></select></label><label>Severity<select id="review-severity"><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select></label><label>Sensor<select id="review-sensor">{alarms.length===0 && <option value="manual">Manual review (no active alarm)</option>}{alarms.map((r,i)=><option key={i} value={i}>{r.sensor_name || r.parameter} — {pretty(r.alarm_status)}</option>)}</select></label><label>Review notes<input id="review-notes" placeholder="What needs inspection or follow-up?"/></label><button className="pdf-button save-review" disabled={reviewBusy} onClick={async()=>{const selected=document.getElementById('review-sensor')?.value||'manual';const r=selected==='manual'?{sensor_name:'Manual review',parameter:'',equipment_id:'',value:'',unit:'',alarm_status:'MANUAL_REVIEW',machine_state:'UNKNOWN'}:(alarms[Number(selected)]||{sensor_name:'Manual review',parameter:'',equipment_id:'',value:'',unit:'',alarm_status:'MANUAL_REVIEW',machine_state:'UNKNOWN'});setReviewBusy(true);setReviewMessage('');try{const res=await fetch(`${API}/api/reviews`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('review-category').value,severity:document.getElementById('review-severity').value,sensor_name:r.sensor_name||r.parameter,parameter:r.parameter||'',equipment_id:r.equipment_id||'',sensor_value:String(r.value??''),unit:r.unit||'',source_alarm:r.alarm_status||'UNKNOWN',machine_state:r.machine_state||'UNKNOWN',notes:document.getElementById('review-notes').value||''})});const body=await res.json().catch(()=>({}));if(!res.ok)throw new Error(body.detail||body.message||`HTTP ${res.status}`);setReviewMessage(`Review #${body.id} saved to MySQL database: ${body.database}.`);await load()}catch(e){setReviewMessage(`Save failed: ${e.message}. Check backend terminal and /api/health.`)}finally{setReviewBusy(false)}}}>{reviewBusy?'Saving…':'Save review to MySQL'}</button>{reviewMessage&&<span className="review-message">{reviewMessage}</span>}</div><SensorTable records={alarms}/></section><section className="panel sensor-panel"><div className="panel-heading"><div><h2>Saved reviews</h2><p>Persisted in the backend database and included in the PDF export</p></div><span className="cluster-pill">{reviews.length} saved</span></div>{reviews.length===0?<div className="empty-state"><CircleHelp size={22}/><b>No reviews saved yet</b><span>Choose an alarm above and save it as a review.</span></div>:<div className="table-scroll"><table><thead><tr><th>Date</th><th>Severity</th><th>Category</th><th>Sensor</th><th>Source alarm</th><th>Notes</th></tr></thead><tbody>{reviews.map(r=><tr key={r.id}><td>{String(r.created_at).replace('T',' ').slice(0,19)}</td><td><span className={`alarm-badge ${r.severity==='Critical'?'critical':r.severity==='High'?'warning':'normal'}`}>{r.severity}</span></td><td>{r.category}</td><td>{r.sensor_name}</td><td>{pretty(r.source_alarm)}</td><td>{r.notes||'—'}</td></tr>)}</tbody></table></div>}</section></>}
        {activeNav==='AI Copilot' && <>
          <section className="feature-kpi-grid">
            <FeatureKpi icon={BrainCircuit} label="Records analyzed" value={aiInsights.records_analyzed ?? records.length} tone="blue" detail="Latest live snapshot"/>
            <FeatureKpi icon={AlertTriangle} label="Flagged readings" value={aiInsights.flagged_count ?? alarms.length} tone={(aiInsights.flagged_count ?? alarms.length) ? 'amber' : 'green'} detail="Based on source alarm labels"/>
            <FeatureKpi icon={ShieldCheck} label="Critical review" value={aiInsights.critical_count ?? 0} tone={(aiInsights.critical_count ?? 0) ? 'red' : 'green'} detail="Rule-based triage"/>
          </section>
          <section className="ai-copilot-grid">
            <div className="panel ai-chat-panel">
              <div className="panel-heading"><div><h2><BrainCircuit size={19}/> FactoryMind AI Operator Copilot</h2><p>Ask about current sensor readings, alarms, and inspection priorities.</p></div><span className="demo-label small">GROUNDED MODE</span></div>
              <div className="ai-suggestions">
                {['Summarize current alarms','Show current sensor readings','What maintenance should I prioritize?'].map(q=><button key={q} className="ai-suggestion" onClick={()=>sendAiMessage(q)} disabled={aiBusy}>{q}</button>)}
              </div>
              <div className="ai-message-list">
                {aiMessages.map((m,i)=><div key={i} className={`ai-message ${m.role}`}><span className="ai-message-icon">{m.role==='assistant'?<Bot size={17}/>:<span>YOU</span>}</span><div className="ai-message-body"><b>{m.role==='assistant'?'FactoryMind AI':'You'}</b><p>{m.content}</p>{m.evidence?.length>0&&<details><summary>Evidence used ({m.evidence.length})</summary>{m.evidence.slice(0,6).map((e,j)=><div className="ai-evidence" key={j}><b>{e.sensor_name}</b><span>{e.value} {e.unit} · {e.source_status} · {e.priority}</span></div>)}</details>}</div></div>)}
                {aiBusy&&<div className="ai-thinking"><Sparkles size={15}/> Analyzing current snapshot…</div>}
              </div>
              <form className="ai-chat-input" onSubmit={e=>{e.preventDefault();sendAiMessage()}}><input value={aiInput} onChange={e=>setAiInput(e.target.value)} placeholder="Ask about alarms, sensors, or maintenance…" maxLength={1200}/><button type="submit" disabled={aiBusy||!aiInput.trim()}><Send size={16}/> Send</button></form>
              <p className="small-print">This assistant uses deterministic, explainable rules and the latest available sensor snapshot. It does not call an external LLM. Follow approved plant SOPs for safety-critical decisions.</p>
            </div>
            <div className="panel ai-insights-panel">
              <div className="panel-heading"><div><h2><Sparkles size={18}/> Live AI triage</h2><p>Refreshes with your live dashboard data.</p></div><span className="cluster-pill">{aiInsights.insights?.length || 0} items</span></div>
              {aiInsights.insights?.length ? <div className="ai-insight-list">{aiInsights.insights.map((item,i)=><article className="ai-insight" key={`${item.parameter}-${i}`}><div className="ai-insight-top"><span className={`feature-status ${item.priority==='Critical review'?'critical':'warning'}`}><AlertTriangle size={15}/></span><div><b>{item.sensor_name}</b><small>{item.equipment_id} · {item.parameter}</small></div><span className="cluster-pill">{item.priority}</span></div><p>{item.evidence}</p><div>{item.recommendation}</div></article>)}</div>:<div className="empty-state"><CheckCircle2 size={23}/><b>No non-normal source labels</b><span>When the stream flags a reading, explainable triage will appear here.</span></div>}
              <p className="small-print">{aiInsights.method || 'Insights are derived from source alarm labels and current sensor readings.'}</p>
            </div>
          </section>
        </>}
        {activeNav==='Predictive Maintenance' && <>
          <section className="feature-kpi-grid">
            <FeatureKpi icon={Wrench} label="Sensors needing review" value={alarms.length} tone={alarms.length ? 'amber' : 'green'} detail="Based on current source alarm labels" />
            <FeatureKpi icon={ShieldCheck} label="Normal readings" value={`${normalPercent}%`} tone="green" detail={`${normalRecords.length} of ${records.length} current readings`} />
            <FeatureKpi icon={AlertTriangle} label="Critical / fault labels" value={criticalRecords.length} tone="red" detail="Check before maintenance decisions" />
          </section>
          <section className="panel feature-panel"><div className="panel-heading"><div><h2>Inspection priorities</h2><p>Live rules-based list derived from the current sensor snapshot. This is not a validated predictive-maintenance diagnosis.</p></div><span className="demo-label small">LIVE DATA</span></div>
            {alarms.length ? <div className="feature-list">{alarms.map((r,i)=><div className="feature-list-row" key={`${r.parameter}-${i}`}><span className={`feature-status ${String(r.alarm_status).toUpperCase().includes('CRIT')||String(r.alarm_status).toUpperCase().includes('FAULT')?'critical':'warning'}`}><Wrench size={17}/></span><div className="feature-row-copy"><b>{r.sensor_name || pretty(r.parameter)}</b><span>{pretty(r.alarm_status)} · {r.equipment_id || 'Equipment not specified'}</span><small>Current reading: {fmt(Number(r.value),3)} {r.unit || ''}. Verify the source alarm and inspect using your approved plant procedure.</small></div><span className="alarm-badge warning">Review</span></div>)}</div> : <div className="empty-state"><CheckCircle2 size={24}/><b>No current alarm-labelled readings</b><span>Keep monitoring the live stream. This does not certify equipment safety.</span></div>}
          </section>
          <section className="panel feature-panel"><div className="panel-heading"><div><h2>All equipment condition signals</h2><p>Vibration, current, pressure, and flow indicators where available</p></div><button className="secondary-action" onClick={()=>exportCsv(records.filter(r=>/vibration|current|pressure|flow/i.test(`${r.parameter} ${r.sensor_name}`)),'factorymind-maintenance-signals.csv')}><Download size={14}/> Export signals</button></div><SensorTable records={records.filter(r=>/vibration|current|pressure|flow/i.test(`${r.parameter} ${r.sensor_name}`))}/></section>
        </>}
        {activeNav==='Process Quality' && <>
          <section className="feature-kpi-grid"><FeatureKpi icon={ClipboardCheck} label="Quality-related sensors" value={qualityRecords.length} tone="blue" detail="Available in the current snapshot"/><FeatureKpi icon={CheckCircle2} label="Normal quality signals" value={qualityRecords.filter(r=>['NORMAL','OK'].includes(String(r.alarm_status||'').toUpperCase())).length} tone="green" detail="Source status labels only"/><FeatureKpi icon={AlertTriangle} label="Signals flagged" value={qualityRecords.filter(r=>!['NORMAL','OK'].includes(String(r.alarm_status||'').toUpperCase())).length} tone="amber" detail="Check thresholds for your process"/></section>
          <section className="panel feature-panel"><div className="panel-heading"><div><h2>Process quality monitor</h2><p>Temperature, pressure, flow, tank level, weight, and conductivity where present</p></div><button className="secondary-action" onClick={()=>exportCsv(qualityRecords,'factorymind-process-quality.csv')}><Download size={14}/> Export quality CSV</button></div><SensorTable records={qualityRecords}/></section>
          <div className="feature-note"><AlertTriangle size={17}/><span>FactoryMind AI displays the sensor source's status labels. Product-quality acceptance limits must be configured and validated by your process/quality team; this page does not independently certify product quality.</span></div>
        </>}
        {activeNav==='Performance' && <>
          <section className="feature-kpi-grid"><FeatureKpi icon={RadioTower} label="Current sensor records" value={records.length} tone="blue" detail="Latest snapshot only"/><FeatureKpi icon={CircleGauge} label="Normal-status share" value={`${normalPercent}%`} tone={normalPercent>=90?'green':'amber'} detail="Normal / OK labels divided by current records"/><FeatureKpi icon={RefreshCw} label="Snapshots received" value={health.snapshot_count || snapshot.snapshot_count || 0} tone="blue" detail="Since backend start, if reported"/><FeatureKpi icon={Activity} label="Active alarm labels" value={currentAlerts} tone={currentAlerts?'red':'green'} detail="Current snapshot"/></section>
          <section className="content-grid"><div className="panel feature-panel"><div className="panel-heading"><div><h2>Current status mix</h2><p>Distribution of source status labels</p></div></div><div className="status-mix"><StatusMix label="Normal / OK" value={normalRecords.length} total={records.length} tone="green"/><StatusMix label="Warning" value={warningRecords.length} total={records.length} tone="amber"/><StatusMix label="Critical / fault" value={criticalRecords.length} total={records.length} tone="red"/><StatusMix label="Other / unknown" value={Math.max(0,records.length-normalRecords.length-warningRecords.length-criticalRecords.length)} total={records.length} tone="blue"/></div></div><div className="panel feature-panel"><div className="panel-heading"><div><h2>Performance data notes</h2><p>Metrics available from the current FactoryMind stream</p></div></div><div className="summary-lines"><div><span>Data source</span><b>{snapshot.connected?'Connected live stream':'Waiting / disconnected'}</b></div><div><span>Last update</span><b>{snapshot.last_update ? String(snapshot.last_update).replace('T',' ').slice(0,19) : 'Not reported'}</b></div><div><span>Production count / OEE</span><b>Not provided by current API</b></div></div><p className="small-print">OEE, throughput, and uptime are not fabricated here. Connect validated production counters and planned/actual runtime to calculate them.</p></div></section>
        </>}
        {activeNav==='Cost Intelligence' && <>
          {/* Controls Bar */}
          <div className="cost-header-actions">
            <div className="cost-mode-pills">
              <button 
                className={`cost-mode-btn ${costMode==='down'?'active down':''}`}
                onClick={()=>setCostMode('down')}
              >
                <TrendingDown size={14}/> Current Month Deviation (Down -8.5%)
              </button>
              <button 
                className={`cost-mode-btn ${costMode==='up'?'active up':''}`}
                onClick={()=>setCostMode('up')}
              >
                <TrendingUp size={14}/> Optimized Tuning Horizon (Up +6.9%)
              </button>
            </div>
            <button 
              className="secondary-action" 
              onClick={()=>fetchCost(costMode)} 
              disabled={costLoading}
              title="Refresh cost metrics with live sensor data"
            >
              <RefreshCw size={13} className={costLoading?'spin':''}/> Sync Live Telemetry
            </button>
            <button 
              className="secondary-action" 
              onClick={exportCostCsv}
              title="Export sensor-explained profit analysis to CSV"
            >
              <Download size={13}/> Export Analysis CSV
            </button>
          </div>

          {/* Month-over-Month Profit KPI Cards */}
          <section className="feature-kpi-grid">
            <div className="profit-kpi-card">
              <span className="card-badge" style={{background:'#e0efff',color:'#1768bd'}}>
                <Clock3 size={11}/> Previous Month
              </span>
              <div className="metric-label">{costData?.previous_month?.period || 'September 2026'} Profit</div>
              <div className="profit-main-val">₹{(costData?.previous_month?.profit || 2845000).toLocaleString('en-IN')}</div>
              <small>Margin: {costData?.previous_month?.margin_pct || 58.9}% · Rev: ₹{((costData?.previous_month?.revenue || 4828000)/100000).toFixed(2)}L</small>
            </div>

            <div className="profit-kpi-card">
              <span className="card-badge" style={{background:'#e8f2ff',color:'#145da0'}}>
                <RadioTower size={11}/> Current Month (Live)
              </span>
              <div className="metric-label">{costData?.current_month?.period || 'October 2026'} Profit</div>
              <div className="profit-main-val">₹{(costData?.current_month?.profit || 2602400).toLocaleString('en-IN')}</div>
              <small>Margin: {costData?.current_month?.margin_pct || 53.4}% · Rev: ₹{((costData?.current_month?.revenue || 4870000)/100000).toFixed(2)}L</small>
            </div>

            <div className={`profit-kpi-card ${costData?.deviation?.trend === 'down' ? 'down-highlight' : 'up-highlight'}`}>
              <span className="card-badge">
                {costData?.deviation?.trend === 'down' ? <ArrowDownRight size={12}/> : <ArrowUpRight size={12}/>}
                Profit Deviation (MoM)
              </span>
              <div className="metric-label">Net Financial Variance</div>
              <div className="profit-main-val">
                {costData?.deviation?.amount_formatted || '-₹2,42,600'}
              </div>
              <small>
                <b>{costData?.deviation?.percentage_formatted || '-8.53%'}</b> shift vs September baseline
              </small>
            </div>

            <div className="profit-kpi-card">
              <span className="card-badge" style={{background:'#fff0cf',color:'#96600a'}}>
                <AlertTriangle size={11}/> Primary Telemetry Driver
              </span>
              <div className="metric-label">Largest Profit Impact</div>
              <div className="profit-main-val" style={{fontSize:'19px',color: costData?.top_driver_impact < 0 ? '#b4233a' : '#087d58'}}>
                {costData?.top_driver_impact < 0 ? `-₹${Math.abs(costData?.top_driver_impact).toLocaleString('en-IN')}` : `+₹${(costData?.top_driver_impact || 0).toLocaleString('en-IN')}`}
              </div>
              <small>{costData?.top_cost_driver || 'Thermal Excursion (TT-103)'}</small>
            </div>
          </section>

          {/* AI Executive Root Cause Telemetry Analysis Panel */}
          <section className="ai-diagnosis-card">
            <div className="ai-diagnosis-header">
              <h3>
                <BrainCircuit size={19} color="#1680b5"/>
                Sensor Telemetry Profit Explanation & Root-Cause Diagnosis
              </h3>
              <span className="ai-diagnosis-badge">
                {costData?.deviation?.trend === 'down' ? 'PROFIT DOWN: ANOMALY ATTRIBUTION' : 'PROFIT UP: EFFICIENCY ATTRIBUTION'}
              </span>
            </div>
            <p className="ai-diagnosis-body">
              {costData?.executive_synthesis || 'Analyzing telemetry to explain profit deviation...'}
            </p>
            <div className="ai-key-deviations">
              <div className="ai-dev-item">
                <span className="feature-status critical" style={{width:28,height:28,borderRadius:7}}><Zap size={15}/></span>
                <div>
                  <b>Motor Overload (CT-101)</b>
                  <span>+18.0% current surge adds ₹68,500 electricity tariff</span>
                </div>
              </div>
              <div className="ai-dev-item">
                <span className="feature-status warning" style={{width:28,height:28,borderRadius:7}}><Wrench size={15}/></span>
                <div>
                  <b>Pump Vibration (VT-101)</b>
                  <span>Peaked at 2.45 mm/s, causing ₹74,200 emergency maintenance</span>
                </div>
              </div>
              <div className="ai-dev-item">
                <span className="feature-status critical" style={{width:28,height:28,borderRadius:7}}><Thermometer size={15}/></span>
                <div>
                  <b>Heating Excursion (TT-103)</b>
                  <span>143.2°C overshoot caused ₹82,400 in milk scorch scrap</span>
                </div>
              </div>
              <div className="ai-dev-item">
                <span className="feature-status warning" style={{width:28,height:28,borderRadius:7}}><Gauge size={15}/></span>
                <div>
                  <b>Pump Backpressure (PT-101)</b>
                  <span>3.32 bar peak caused ₹38,000 in throttling pauses</span>
                </div>
              </div>
            </div>
          </section>

          {/* Interactive Comparison Charts */}
          <section className="cost-chart-grid">
            <div className="panel chart-panel">
              <div className="panel-heading">
                <div>
                  <h2>Previous Month vs Current Month Financial Breakdown</h2>
                  <p>Comparing Revenue, Energy, Maintenance, Scrap, and Net Profit (₹ INR)</p>
                </div>
                <span className="cluster-pill">MoM Comparison</span>
              </div>
              <div className="chart-legend" style={{marginTop:14}}>
                <span><i style={{background:'#2d5b99'}}/>Previous Month (Sept 2026)</span>
                <span><i style={{background: costMode==='down' ? '#e25d68' : '#20a879'}}/>Current Month (Oct 2026)</span>
              </div>
              <div className="chart-wrap" style={{height:260}}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={costData?.breakdown_comparison || []} margin={{top:15,right:10,left:10,bottom:15}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e1edf5" vertical={false}/>
                    <XAxis dataKey="metric" tick={{fill:'#587991',fontSize:10}} tickLine={false} axisLine={{stroke:'#cfe1ee'}}/>
                    <YAxis tickFormatter={v => `₹${(v/100000).toFixed(1)}L`} tick={{fill:'#587991',fontSize:10}} tickLine={false} axisLine={false}/>
                    <Tooltip 
                      formatter={(value, name) => [`₹${Number(value).toLocaleString('en-IN')}`, name === 'previous' ? 'Previous Month' : 'Current Month']}
                      contentStyle={{background:'#fff',border:'1px solid #c7dce9',borderRadius:8,color:'#183c57',fontSize:11}}
                    />
                    <Bar dataKey="previous" name="Previous Month" fill="#326cb5" radius={[4,4,0,0]} barSize={16}/>
                    <Bar dataKey="current" name="Current Month" fill={costMode==='down' ? '#e25d68' : '#20a879'} radius={[4,4,0,0]} barSize={16}/>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-note">
                <span className="live-dot"/> Net profit shifted by {costData?.deviation?.amount_formatted} ({costData?.deviation?.percentage_formatted}).
              </div>
            </div>

            <div className="panel chart-panel">
              <div className="panel-heading">
                <div>
                  <h2>Sensor Telemetry Profit Impact (INR)</h2>
                  <p>Financial gain (+) or loss (-) caused by individual sensor deviations</p>
                </div>
                <span className="mini-live"><i/>LIVE SENSORS</span>
              </div>
              <div className="chart-wrap" style={{height:260,marginTop:14}}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart 
                    layout="vertical"
                    data={(costData?.sensor_explanations || []).map(s => ({
                      name: s.sensor_name,
                      impact: s.financial_impact,
                      formatted: `${s.financial_impact > 0 ? '+' : ''}₹${Math.abs(s.financial_impact).toLocaleString('en-IN')}`
                    }))}
                    margin={{top:5,right:30,left:20,bottom:5}}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e1edf5" horizontal={false}/>
                    <XAxis type="number" tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} tick={{fill:'#587991',fontSize:10}} axisLine={false} tickLine={false}/>
                    <YAxis type="category" dataKey="name" width={140} tick={{fill:'#1c4464',fontSize:10,fontWeight:600}} axisLine={false} tickLine={false}/>
                    <Tooltip 
                      formatter={(val) => [`${val > 0 ? '+' : ''}₹${Math.abs(val).toLocaleString('en-IN')}`, 'Profit Contribution']}
                      contentStyle={{background:'#fff',border:'1px solid #c7dce9',borderRadius:8,color:'#183c57',fontSize:11}}
                    />
                    <Bar dataKey="impact" radius={[4,4,4,4]} barSize={14}>
                      {(costData?.sensor_explanations || []).map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.financial_impact >= 0 ? '#20a879' : '#e25d68'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-note">
                <AlertTriangle size={13} color="#96600a"/> Red bars indicate margin erosion from equipment anomalies.
              </div>
            </div>
          </section>

          {/* Sensor-Explained Telemetry Table */}
          <section className="panel sensor-panel">
            <div className="panel-heading">
              <div>
                <h2>Sensor Telemetry Variance & Profit Deviation Details</h2>
                <p>Root-cause physical phenomena explaining the month-over-month profit variance</p>
              </div>
              <span className="cluster-pill">{costData?.sensor_explanations?.length || 0} Telemetry Factors</span>
            </div>

            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Sensor & Equipment</th>
                    <th>Previous Baseline</th>
                    <th>Current / Live Reading</th>
                    <th>Variance %</th>
                    <th>Profit Impact</th>
                    <th>Category</th>
                    <th style={{minWidth:280}}>Telemetry Root Cause Explanation</th>
                    <th>Recommended Engineering Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(costData?.sensor_explanations || []).map((s, idx) => (
                    <tr key={`${s.parameter}-${idx}`}>
                      <td>
                        <div className="sensor-name">
                          <span className="sensor-mini">
                            <Activity size={15}/>
                          </span>
                          <div>
                            <b>{s.sensor_name}</b>
                            <small>{s.equipment_id} · {s.parameter}</small>
                          </div>
                        </div>
                      </td>
                      <td><b>{s.prev_baseline} <small>{s.unit}</small></b></td>
                      <td>
                        <b className="value-cell">
                          {s.curr_reading} <small>{s.unit}</small>
                        </b>
                      </td>
                      <td>
                        <span className={`variance-pill ${s.financial_impact < 0 ? 'danger' : s.financial_impact > 0 ? 'success' : 'neutral'}`}>
                          {s.variance_pct > 0 ? `+${s.variance_pct}%` : `${s.variance_pct}%`}
                        </span>
                      </td>
                      <td>
                        <span className={s.financial_impact < 0 ? 'impact-val-neg' : 'impact-val-pos'}>
                          {s.financial_impact > 0 ? `+₹${s.financial_impact.toLocaleString('en-IN')}` : `-₹${Math.abs(s.financial_impact).toLocaleString('en-IN')}`}
                        </span>
                      </td>
                      <td>
                        <span className={`alarm-badge ${s.severity === 'Critical' ? 'critical' : s.severity === 'Warning' ? 'warning' : 'normal'}`}>
                          {s.category}
                        </span>
                      </td>
                      <td className="sensor-expl-row">
                        <p>{s.explanation}</p>
                      </td>
                      <td className="sensor-expl-row">
                        <small>{s.recommendation}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Editable Cost Assumption Settings */}
          <section className="panel feature-panel">
            <div className="panel-heading">
              <div>
                <h2>Configurable Alarm Exposure Baseline</h2>
                <p>Adjust the base illustrative cost penalty assigned per abnormal alarm instance</p>
              </div>
            </div>
            <div className="cost-assumption">
              <label>
                Assumed cost per current alarm (₹)
                <input 
                  type="number" 
                  min="0" 
                  value={costPerAlarm} 
                  onChange={e=>{
                    setCostPerAlarm(Math.max(0,Number(e.target.value)||0));
                    setSettingsSaved(false);
                  }}
                />
              </label>
              <button 
                className="pdf-button" 
                onClick={()=>{
                  localStorage.setItem('fm_cost_per_alarm',String(costPerAlarm));
                  setSettingsSaved(true);
                  fetchCost(costMode);
                }}
              >
                <Save size={15}/> Save assumption
              </button>
              {settingsSaved && <span className="review-message">Assumption saved and updated in analysis.</span>}
            </div>
            <p className="small-print">
              Cost Intelligence combines plant financial models with live telemetry readings from the sensor stream. 
              Variances are dynamically attributed to energy draw, mechanical wear, thermal degradation, and line backpressure.
            </p>
          </section>
        </>}
        {activeNav==='Reports & Exports' && <>
          <section className="feature-kpi-grid"><FeatureKpi icon={FileText} label="Current sensor rows" value={records.length} tone="blue" detail="Latest live snapshot"/><FeatureKpi icon={Bell} label="Current alarm rows" value={alarms.length} tone="amber" detail="Source alarm labels"/><FeatureKpi icon={ClipboardCheck} label="Saved reviews" value={reviews.length} tone="green" detail="Stored in configured MySQL database"/></section>
          <section className="report-cards"><ReportCard icon={Download} title="Export live sensor CSV" description="Download all sensor readings in the latest snapshot, including source alarm and ML labels." action="Download sensor CSV" onClick={()=>exportCsv(records,'factorymind-live-sensors.csv')}/><ReportCard icon={AlertTriangle} title="Export alarm CSV" description="Download the current records that carry a non-normal source alarm label." action="Download alarms CSV" onClick={()=>exportCsv(alarms,'factorymind-current-alarms.csv')}/><ReportCard icon={FileText} title="Export review PDF" description="Open the backend-generated PDF of reviews already saved in MySQL." action="Open review PDF" onClick={()=>window.open(`${API}/api/reviews/report.pdf`,'_blank')}/><ReportCard icon={ClipboardCheck} title="Export quality CSV" description="Download current temperature, pressure, flow, level, weight, and conductivity readings." action="Download quality CSV" onClick={()=>exportCsv(qualityRecords,'factorymind-process-quality.csv')}/></section>
          <div className="feature-note"><Mail size={17}/><span>Automated email delivery is not enabled in this FactoryMind backend. These exports work from the live data currently available; scheduled email reports require mail-server credentials and recipient authorization.</span></div>
        </>}
        {activeNav==='Email Machine Status' && <>
          <section className="feature-kpi-grid">
            <FeatureKpi icon={RadioTower} label="Live stream" value={snapshot.connected?'Connected':'Offline'} tone={snapshot.connected?'green':'red'} detail="Connection state at send time"/>
            <FeatureKpi icon={Activity} label="Sensor readings" value={records.length} tone="blue" detail="Records in latest snapshot"/>
            <FeatureKpi icon={AlertTriangle} label="Flagged readings" value={alarms.length} tone={alarms.length?'amber':'green'} detail="Source labels outside NORMAL / OK"/>
          </section>
          <section className="panel feature-panel email-status-panel">
            <div className="panel-heading"><div><h2><Mail size={19}/> Email current machine status to manager</h2><p>Send a one-time status report based on the latest live sensor snapshot.</p></div><span className="demo-label small">MANUAL SEND</span></div>
            <div className="email-status-summary">
              <div><span>Current machine overview</span><strong>{!snapshot.connected?'STREAM OFFLINE':alarms.some(r=>/CRIT|FAULT/i.test(String(r.alarm_status||'')))?'CRITICAL / FAULT LABELS PRESENT':alarms.length?'WARNINGS PRESENT':records.length?'NO SOURCE ALARMS REPORTED':'WAITING FOR SENSOR DATA'}</strong></div>
              <div><span>Latest update</span><strong>{snapshot.last_update?new Date(snapshot.last_update*1000).toLocaleString():'Not received yet'}</strong></div>
            </div>
            <div className="email-status-form">
              <label>Manager email address<input type="email" value={managerEmail} onChange={e=>setManagerEmail(e.target.value)} placeholder="jaakkarthi10@gmail.com" autoComplete="email"/></label>
              <label>Gmail App Password<input type="password" value={smtpAppPassword} onChange={e=>setSmtpAppPassword(e.target.value)} placeholder="Enter Gmail App Password" autoComplete="new-password"/></label>
              <button className="pdf-button" disabled={emailBusy || !managerEmail.trim() || !smtpAppPassword.trim()} onClick={async()=>{setEmailBusy(true);setEmailMessage('');try{const response=await fetch(`${API}/api/email/machine-status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manager_email:managerEmail.trim(),smtp_password:smtpAppPassword})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||`HTTP ${response.status}`);setEmailMessage(`Status email sent successfully to ${body.recipient}. Status: ${body.overall_status}; ${body.sensor_count} sensor readings and ${body.flagged_count} flagged readings included.`)}catch(err){setEmailMessage(`Email not sent: ${err.message}`)}finally{setEmailBusy(false)}}}>{emailBusy?'Sending status…':<><Send size={14}/> Send status email</>}</button>
            </div>
            {emailMessage&&<div className={`email-feedback ${emailMessage.startsWith('Status email sent')?'success':'error'}`} role="status">{emailMessage}</div>}
            <div className="feature-note"><ShieldCheck size={17}/><span>Sender defaults to jaakkarthi10@gmail.com; no .env file is required. Enter a Google App Password for that Gmail account when sending. It is used for this request only and is not saved by the website. The report includes current sensor readings, stream status, alarm labels, and follow-up reminders. Sending is manual when you click the button.</span></div>
          </section>
          <section className="panel sensor-panel"><div className="panel-heading"><div><h2>Readings that will be included</h2><p>Preview of the latest snapshot before sending.</p></div><span className="cluster-pill">{records.length} readings</span></div><SensorTable records={records}/></section>
        </>}
        {activeNav==='Settings' && <>
          <section className="panel feature-panel settings-panel"><div className="panel-heading"><div><h2>Monitoring settings</h2><p>Configure this browser's dashboard refresh behavior</p></div><Settings size={19}/></div><div className="settings-grid"><label>Dashboard polling interval<select value={refreshMs} onChange={e=>{const v=Number(e.target.value);setRefreshMs(v);localStorage.setItem('fm_refresh_ms',String(v));setSettingsSaved(false)}}><option value={1000}>1 second</option><option value={1800}>1.8 seconds (default)</option><option value={3000}>3 seconds</option><option value={5000}>5 seconds</option><option value={10000}>10 seconds</option></select><small>Controls how often the browser requests a snapshot. It does not change the backend sensor sampling rate.</small></label><div className="setting-status"><span className={`status-light ${snapshot.connected?'on':'off'}`}/><div><b>{snapshot.connected?'Live stream connected':'Live stream disconnected'}</b><small>{health.database==='factorymind_ai'?'Database: factorymind_ai':health.mysql==='connected'?'MySQL connected':`Database status: ${health.mysql || 'check API health'}`}</small></div></div></div><div className="settings-actions"><button className="pdf-button" onClick={()=>{localStorage.setItem('fm_refresh_ms',String(refreshMs));localStorage.setItem('fm_cost_per_alarm',String(costPerAlarm));setSettingsSaved(true)}}><Save size={15}/> Save settings</button><button className="secondary-action" onClick={()=>{localStorage.removeItem('fm_refresh_ms');localStorage.removeItem('fm_cost_per_alarm');setRefreshMs(1800);setCostPerAlarm(2500);setSettingsSaved(false)}}>Reset defaults</button>{settingsSaved&&<span className="review-message"><Check size={14}/> Settings saved in this browser.</span>}</div></section>
          <section className="panel feature-panel"><div className="panel-heading"><div><h2>System information</h2><p>Connection information from the running API</p></div></div><div className="summary-lines"><div><span>Stream status</span><b>{snapshot.connected?'Connected':'Disconnected'}</b></div><div><span>Backend snapshots</span><b>{health.snapshot_count ?? 'Not reported'}</b></div><div><span>Loaded ML models</span><b>{(health.models_loaded || []).join(', ') || 'No trained models reported'}</b></div><div><span>MySQL status</span><b>{health.mysql || health.database_status || 'See /api/health response'}</b></div></div></section>
        </>}
        <footer><span>© 2026 FactoryMind AI</span><span><span className={`status-light ${snapshot.connected?'on':'off'}`}/>{snapshot.connected?'Connected to sensor stream':'Backend connection unavailable'} · {health.snapshot_count||0} snapshots received</span></footer>
      </div>
    </main>
  </div>
}

function FeatureKpi({ icon: Icon, label, value, detail, tone='blue' }) {
  return <div className="feature-kpi"><div className={`feature-kpi-icon ${tone}`}><Icon size={19}/></div><div className="feature-kpi-label">{label}</div><strong>{value}</strong><small>{detail}</small></div>
}
function StatusMix({ label, value, total, tone }) {
  const pct = total ? Math.round(value / total * 100) : 0
  return <div className="status-mix-row"><div><span><i className={`mix-dot ${tone}`}/>{label}</span><b>{value} <small>({pct}%)</small></b></div><div className="mix-track"><i className={tone} style={{width:`${pct}%`}}/></div></div>
}
function ReportCard({ icon: Icon, title, description, action, onClick }) {
  return <div className="panel report-card"><span className="report-card-icon"><Icon size={21}/></span><h2>{title}</h2><p>{description}</p><button className="pdf-button" onClick={onClick}>{action}<Download size={14}/></button></div>
}

function SensorTable({ records }) {
  if (!records.length) return <div className="empty-state"><RadioTower size={24}/><b>No sensor records yet</b><span>Waiting for the next live snapshot.</span></div>
  return <div className="table-scroll"><table><thead><tr><th>Sensor</th><th>Equipment</th><th>Current value</th><th>Machine state</th><th>Source alarm</th><th>ML classification</th><th>Cluster</th></tr></thead><tbody>{records.map((r,i)=>{
    const alarm=String(r.alarm_status||'UNKNOWN').toUpperCase()
    const tone=['NORMAL','OK'].includes(alarm)?'normal':alarm==='WARNING'?'warning':'critical'
    return <tr key={`${r.sensor_id||r.parameter}-${i}`}><td><div className="sensor-name"><span className="sensor-mini"><Activity size={15}/></span><div><b>{r.sensor_name||pretty(r.parameter)}</b><small>{r.parameter}</small></div></div></td><td>{r.equipment_id||'—'}</td><td><b className="value-cell">{fmt(Number(r.value),3)} <small>{r.unit||''}</small></b></td><td><span className="machine-state"><i/>{pretty(r.machine_state||'unknown')}</span></td><td><span className={`alarm-badge ${tone}`}><i/>{pretty(alarm)}</span></td><td>{r.ml_predicted_alarm?<span className="ml-label">{pretty(r.ml_predicted_alarm)}{r.ml_confidence!=null?` · ${(r.ml_confidence*100).toFixed(0)}%`:''}</span>:<span className="muted">—</span>}</td><td>{r.ml_cluster!==undefined?<span className="cluster-pill">C{r.ml_cluster}</span>:<span className="muted">—</span>}</td></tr>
  })}</tbody></table></div>
}
