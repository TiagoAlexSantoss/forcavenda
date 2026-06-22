import React, { useContext, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Bot, Box, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, CreditCard, Edit3, Filter, HelpCircle, Home, Layers3, LockKeyhole, LogOut, Mail, Menu, Moon, Package, Plus, RefreshCcw, Search, Send, Sun, Tags, Trash2, Users, X, XCircle } from "lucide-react";
import api from "./services/api";
import "./styles.css";

const today = new Date().toISOString().slice(0, 10);
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const percent = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const BrowserDefinitionsContext = React.createContext([]);
const GlobalSearchContext = React.createContext("");

const TAB_ACCESS = {
  products: "sales_products",
  priceTables: "sales_price_tables",
  groups: "sales_product_groups",
  classes: "sales_product_classes",
  customers: "sales_customers",
  customerProfiles: "sales_customer_profiles",
  salesRepresentatives: "sales_representatives",
  orders: "sales_orders",
  customerManagement: "sales_customer_management",
  approvals: "sales_approvals",
  orderAssistant: "sales_order_assistant",
};

const emptyCustomer = { customer_profile_id: "", name: "", document_number: "", email: "", phone: "", city: "", state_code: "", active: true };
const emptyCustomerProfile = { code: "", name: "", description: "", max_inactive_days: "180", max_overdue_days: "0", block_without_movement: false, block_overdue_titles: true, active: true, payment_rules: [] };
const emptyProfilePaymentRule = { payment_method: "avista", max_installments: "1", max_total_days: "0", active: true };
const emptyGroup = { code: "", name: "", description: "", active: true };
const emptyClass = { product_group_id: "", code: "", name: "", description: "", active: true };
const emptyProduct = { product_group_id: "", product_class_id: "", sku: "", name: "", unit: "UN", purchase_price: "0.00", cost_price: "0.00", suggested_margin_percent: "0.00", sale_price: "0.00", default_warehouse_id: "", description: "", active: true };
const emptyPriceTable = { code: "", name: "", correction_mode: "outside", monthly_rate: "0.00", base_date: today, active: true };
const emptyPriceItem = { product_id: "", base_price: "0.00", margin_percent: "5.00", active: true };
const emptyPriceTier = { min_quantity: "1.00", discount_percent: "0.00", active: true };
const emptyOrder = { customer_id: "", sales_representative_id: "", price_table_id: "", order_type: "sale", order_date: today, payment_due_date: today, delivery_date: "", notes: "" };
const emptySalesRepresentative = { user_id: "", code: "", whatsapp_number: "", active: true, customer_ids: [] };
const emptyOrderItem = { product_id: "", warehouse_id: "", quantity: "1", negotiated_unit_price: "" };
const emptyPaymentSuggestion = { payment_method: "avista", due_date: today, amount: "0.00", notes: "" };

const MESSAGE_TYPES = {
  error: "error",
  success: "success",
};

const MESSAGES = {
  apiUnavailable: "Nao foi possivel conectar na API do EasySales.",
  operationFailed: "Nao foi possivel concluir a operacao.",
  operationSuccess: "Operacao concluida com sucesso.",
  customers: {
    profileRequired: "Informe o perfil comercial do cliente.",
  },
};

function createMessage(type, text) {
  return { type, text };
}

function errorMessage(error, fallback = MESSAGES.operationFailed) {
  return createMessage(MESSAGE_TYPES.error, error?.response?.data?.detail || error?.message || fallback);
}

function readStoredUser() {
  if (!localStorage.getItem("easysales_token")) return null;
  try {
    return JSON.parse(localStorage.getItem("easysales_user") || "null");
  } catch {
    return null;
  }
}

function LoginPage({ onLogin, message, loading }) {
  const [form, setForm] = useState({ email: localStorage.getItem("easysales_last_email") || "", password: "" });
  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-mark"><Package size={30} /></div>
        <p className="eyebrow">Operacao comercial integrada</p>
        <h1>EasySales</h1>
        <p className="lead">Pedidos, carteira, precos e autorizacoes com acesso centralizado.</p>
        {message && <div className={`message ${message.type}`}>{message.text}</div>}
        <form className="login-form" onSubmit={(event) => { event.preventDefault(); onLogin(form); }}>
          <label><span>E-mail</span><div className="input-wrap"><Mail size={18} /><input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} autoComplete="username" required /></div></label>
          <label><span>Senha</span><div className="input-wrap"><LockKeyhole size={18} /><input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} autoComplete="current-password" required /></div></label>
          <button type="submit" disabled={loading}>{loading ? "Entrando..." : "Entrar no EasySales"}</button>
        </form>
      </section>
    </main>
  );
}

function App() {
  const [currentUser, setCurrentUser] = useState(() => readStoredUser());
  const [loginMessage, setLoginMessage] = useState(null);
  const [loginLoading, setLoginLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const [theme, setTheme] = useState(() => localStorage.getItem("easysales-theme") || "light");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState({ cadastros: true, operacoes: true });
  const [health, setHealth] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [activeCompanyId, setActiveCompanyId] = useState(() => localStorage.getItem("easy-active-company-id") || "");
  const [toasts, setToasts] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [salesRepresentatives, setSalesRepresentatives] = useState([]);
  const [userOptions, setUserOptions] = useState([]);
  const [customerProfiles, setCustomerProfiles] = useState([]);
  const [groups, setGroups] = useState([]);
  const [classes, setClasses] = useState([]);
  const [products, setProducts] = useState([]);
  const [priceTables, setPriceTables] = useState([]);
  const [orders, setOrders] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [balances, setBalances] = useState([]);
  const [movements, setMovements] = useState([]);
  const [customerMonitoring, setCustomerMonitoring] = useState([]);
  const [assistantStatus, setAssistantStatus] = useState(null);
  const [controlBrowsers, setControlBrowsers] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  useEffect(() => {
    if (!currentUser) return;
    api.get("/auth/me")
      .then((response) => {
        setCurrentUser(response.data);
        localStorage.setItem("easysales_user", JSON.stringify(response.data));
      })
      .catch(logout);
  }, []);

  useEffect(() => {
    if (currentUser) loadAll();
  }, [currentUser?.id, JSON.stringify(currentUser?.permissions || {})]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("easysales-theme", theme);
  }, [theme]);

  async function loadAll() {
    try {
      const empty = { data: [] };
      const fetchIf = (allowed, path) => allowed ? api.get(path) : Promise.resolve(empty);
      const [healthRes, companiesRes, customersRes, representativesRes, usersRes, monitoringRes, profilesRes, groupsRes, classesRes, productsRes, priceTablesRes, ordersRes, warehousesRes, balancesRes, movementsRes, assistantRes, browsersRes] = await Promise.all([
        api.get("/health"),
        api.get("/companies"),
        fetchIf(can("sales_customers") || can("sales_orders"), "/customers"),
        fetchIf(can("sales_representatives") || can("sales_orders"), "/sales-representatives"),
        fetchIf(can("sales_representatives") || can("sales_orders"), "/users/options"),
        fetchIf(can("sales_customer_management"), "/customer-monitoring"),
        fetchIf(can("sales_customer_profiles"), "/customer-profiles"),
        fetchIf(can("sales_product_groups"), "/product-groups"),
        fetchIf(can("sales_product_classes"), "/product-classes"),
        fetchIf(can("sales_products") || can("sales_orders"), "/products"),
        fetchIf(can("sales_price_tables") || can("sales_orders"), "/price-tables"),
        fetchIf(can("sales_orders") || can("sales_approvals"), "/orders"),
        fetchIf(can("sales_products") || can("sales_orders"), "/warehouses"),
        fetchIf(can("sales_products"), "/stock-balances"),
        fetchIf(can("sales_products"), "/stock-movements"),
        fetchIf(can("sales_order_assistant"), "/assistant/status"),
        fetchIf(can("sales_browser_definitions"), "/control/browser-definitions"),
      ]);
      setHealth(healthRes.data);
      setCompanies(companiesRes.data);
      if (!localStorage.getItem("easy-active-company-id") && companiesRes.data[0]?.id) {
        localStorage.setItem("easy-active-company-id", String(companiesRes.data[0].id));
        setActiveCompanyId(String(companiesRes.data[0].id));
      }
      setCustomers(customersRes.data);
      setSalesRepresentatives(representativesRes.data);
      setUserOptions(usersRes.data);
      setCustomerMonitoring(monitoringRes.data);
      setCustomerProfiles(profilesRes.data);
      setGroups(groupsRes.data);
      setClasses(classesRes.data);
      setProducts(productsRes.data);
      setPriceTables(priceTablesRes.data);
      setOrders(ordersRes.data);
      setWarehouses(warehousesRes.data);
      setBalances(balancesRes.data);
      setMovements(movementsRes.data);
      setAssistantStatus(assistantRes.data);
      setControlBrowsers(browsersRes.data);
    } catch (error) {
      pushToast(errorMessage(error, MESSAGES.apiUnavailable));
    }
  }

  function openTab(tab) {
    if (tab !== "home" && !can(TAB_ACCESS[tab])) return;
    setActiveTab(tab);
  }

  function can(scope, action = "view") {
    if (!scope) return true;
    return (currentUser?.permissions?.[scope] || []).includes(action);
  }

  async function login(form) {
    setLoginLoading(true);
    setLoginMessage(null);
    try {
      const response = await api.post("/auth/login", form);
      localStorage.setItem("easysales_token", response.data.access_token);
      localStorage.setItem("easysales_user", JSON.stringify(response.data.user));
      localStorage.setItem("easysales_last_email", form.email);
      setCurrentUser(response.data.user);
    } catch (error) {
      setLoginMessage(errorMessage(error, "Nao foi possivel entrar."));
    } finally {
      setLoginLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem("easysales_token");
    localStorage.removeItem("easysales_user");
    setCurrentUser(null);
  }

  function changeCompany(companyId) {
    localStorage.setItem("easy-active-company-id", companyId);
    setActiveCompanyId(companyId);
    window.setTimeout(loadAll, 0);
  }

  const pageMetadata = {
    home: ["Visao geral", "Home"],
    products: ["Cadastros", "Produtos"],
    priceTables: ["Cadastros", "Tabelas de preco"],
    groups: ["Cadastros", "Grupos de produtos"],
    classes: ["Cadastros", "Classes de produtos"],
    customers: ["Cadastros", "Clientes"],
    customerProfiles: ["Cadastros", "Perfis comerciais"],
    salesRepresentatives: ["Cadastros", "Vendedores"],
    orders: ["Operacoes", "Pedidos"],
    customerManagement: ["Operacoes", "Gestao de clientes"],
    approvals: ["Operacoes", "Autorizacoes"],
    orderAssistant: ["Operacoes", "Assistente WhatsApp"],
  };
  const pageMeta = pageMetadata[activeTab] || ["EasySales", "EasySales"];

  async function run(action) {
    try {
      const result = await action();
      await loadAll();
      pushToast(createMessage(MESSAGE_TYPES.success, MESSAGES.operationSuccess));
      return result || true;
    } catch (error) {
      pushToast(errorMessage(error));
      return false;
    }
  }

  function pushToast(message) {
    const id = `${Date.now()}-${Math.random()}`;
    const toast = { ...message, id };
    setToasts((current) => [toast, ...current].slice(0, 5));
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }

  if (!currentUser) return <LoginPage onLogin={login} message={loginMessage} loading={loginLoading} />;

  const searchResults = searchTerm.trim()
    ? Object.entries(pageMetadata)
      .map(([tab, meta]) => ({ tab, section: meta[0], label: meta[1] }))
      .filter((item) => item.tab === "home" || can(TAB_ACCESS[item.tab]))
      .filter((item) => `${item.label} ${item.section}`.toLowerCase().includes(searchTerm.trim().toLowerCase()))
      .slice(0, 8)
    : [];

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <Package size={24} />
          <div>
            <strong>EasySales</strong>
            <span>{health?.customer_provider === "easyfinance" ? "Integrado ao EasyFinance" : "Operacao independente"}</span>
          </div>
          <button type="button" className="sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} title="Recolher menu"><Menu size={22} /></button>
        </div>

        <NavButton active={activeTab === "home"} onClick={() => openTab("home")} icon={Home} label="Home" />

        {(can("sales_products") || can("sales_price_tables") || can("sales_product_groups") || can("sales_product_classes") || can("sales_customers") || can("sales_customer_profiles") || can("sales_representatives")) && (
          <MenuGroup title="Cadastros" open={menuOpen.cadastros} collapsed={sidebarCollapsed} onToggle={() => setMenuOpen((current) => ({ ...current, cadastros: !current.cadastros }))}>
            {can("sales_products") && <NavButton active={activeTab === "products"} onClick={() => openTab("products")} icon={Box} label="Produtos" />}
            {can("sales_price_tables") && <NavButton active={activeTab === "priceTables"} onClick={() => openTab("priceTables")} icon={Tags} label="Tabelas de preco" />}
            {can("sales_product_groups") && <NavButton active={activeTab === "groups"} onClick={() => openTab("groups")} icon={Layers3} label="Grupos" />}
            {can("sales_product_classes") && <NavButton active={activeTab === "classes"} onClick={() => openTab("classes")} icon={Layers3} label="Classes" />}
            {can("sales_customers") && <NavButton active={activeTab === "customers"} onClick={() => openTab("customers")} icon={Users} label="Clientes" />}
            {can("sales_customer_profiles") && <NavButton active={activeTab === "customerProfiles"} onClick={() => openTab("customerProfiles")} icon={Users} label="Perfis comerciais" />}
            {can("sales_representatives") && <NavButton active={activeTab === "salesRepresentatives"} onClick={() => openTab("salesRepresentatives")} icon={Users} label="Vendedores" />}
          </MenuGroup>
        )}

        <MenuGroup title="Operacoes" open={menuOpen.operacoes} collapsed={sidebarCollapsed} onToggle={() => setMenuOpen((current) => ({ ...current, operacoes: !current.operacoes }))}>
          {can("sales_orders") && <NavButton active={activeTab === "orders"} onClick={() => openTab("orders")} icon={ClipboardList} label="Pedidos" />}
          {can("sales_customer_management") && <NavButton active={activeTab === "customerManagement"} onClick={() => openTab("customerManagement")} icon={Users} label="Gestao clientes" />}
          {can("sales_approvals") && <NavButton active={activeTab === "approvals"} onClick={() => openTab("approvals")} icon={CheckCircle2} label="Autorizacoes" />}
          {can("sales_order_assistant") && <NavButton active={activeTab === "orderAssistant"} onClick={() => openTab("orderAssistant")} icon={Bot} label="Assistente WhatsApp" />}
        </MenuGroup>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar-search">
            <div className="search-box">
              <Search size={18} />
              <input value={searchTerm} onFocus={() => setSearchOpen(true)} onChange={(event) => { setSearchTerm(event.target.value); setSearchOpen(true); }} placeholder="Buscar tela, cadastro ou operacao..." />
            </div>
            {searchOpen && searchTerm.trim() && (
              <div className="search-results">
                {searchResults.map((item) => <button key={item.tab} type="button" onClick={() => { openTab(item.tab); setSearchOpen(false); setSearchTerm(""); }}><strong>{item.label}</strong><span>{item.section}</span></button>)}
                {!searchResults.length && <span className="search-empty">Nenhuma tela encontrada.</span>}
              </div>
            )}
          </div>
          <div className="topbar-actions">
            <select className="company-select" value={activeCompanyId} onChange={(event) => changeCompany(event.target.value)}>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.code} - {company.name}</option>)}
            </select>
            <button className="secondary-button" onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />} {theme === "dark" ? "Claro" : "Escuro"}
            </button>
            <button className="secondary-button" onClick={loadAll}><RefreshCcw size={17} /> Atualizar</button>
            <div className="user-menu">
              <button className="user-button" type="button" onClick={() => setUserMenuOpen((value) => !value)}>
                <span className="avatar">{currentUser.name.slice(0, 1).toUpperCase()}</span>
                <span><strong>{currentUser.name}</strong><small>{currentUser.email}</small></span>
                <ChevronDown size={16} />
              </button>
              {userMenuOpen && <div className="user-dropdown"><button type="button" onClick={logout}><LogOut size={16} /> Sair</button></div>}
            </div>
          </div>
        </header>

        {toasts.length > 0 && (
          <div className="toast-stack">
            {toasts.map((toast) => <div key={toast.id} className={`message ${toast.type}`}>{toast.text}</div>)}
          </div>
        )}

        <GlobalSearchContext.Provider value={activeTab === "home" ? "" : searchTerm}>
        <BrowserDefinitionsContext.Provider value={controlBrowsers}>
          {activeTab === "home" && <HomePage orders={orders} customers={customers} products={products} priceTables={priceTables} customerMonitoring={customerMonitoring} openTab={openTab} />}
          {activeTab === "products" && <ProductsBrowser products={products} groups={groups} classes={classes} warehouses={warehouses} balances={balances} movements={movements} companies={companies} run={run} />}
          {activeTab === "priceTables" && <PriceTablesBrowser priceTables={priceTables} products={products} companies={companies} run={run} />}
          {activeTab === "groups" && <SimpleCatalogBrowser title="Grupos de produtos" eyebrow="Cadastros" endpoint="/product-groups" entityCode="product_groups" items={groups} template={emptyGroup} companies={companies} companyEndpoint="/product-groups" run={run} />}
          {activeTab === "classes" && <ClassesBrowser classes={classes} groups={groups} companies={companies} run={run} />}
          {activeTab === "customers" && <CustomersBrowser customers={customers} customerProfiles={customerProfiles} salesRepresentatives={salesRepresentatives} companies={companies} run={run} />}
          {activeTab === "customerProfiles" && <CustomerProfilesBrowser profiles={customerProfiles} run={run} />}
          {activeTab === "salesRepresentatives" && <SalesRepresentativesBrowser representatives={salesRepresentatives} users={userOptions} run={run} />}
          {activeTab === "orders" && <OrdersBrowser orders={orders} customers={customers} salesRepresentatives={salesRepresentatives} products={products} priceTables={priceTables} warehouses={warehouses} run={run} />}
          {activeTab === "customerManagement" && <CustomerManagementPage rows={customerMonitoring} run={run} />}
          {activeTab === "approvals" && <OrderApprovalsPage orders={orders} run={run} />}
          {activeTab === "orderAssistant" && <OrderAssistantStatusPage status={assistantStatus} />}
        </BrowserDefinitionsContext.Provider>
        </GlobalSearchContext.Provider>
      </main>
    </div>
  );
}

function MenuGroup({ title, open, collapsed, onToggle, children }) {
  return (
    <div className="menu-group">
      <button type="button" className="menu-section" onClick={onToggle} title={title}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <span>{title}</span>
      </button>
      {(open || collapsed) && <div className="menu-items">{children}</div>}
    </div>
  );
}

function NavButton({ active, onClick, icon: Icon, label }) {
  return <button className={active ? "active" : ""} onClick={onClick} title={label}><Icon size={18} /> <span>{label}</span></button>;
}

function HomePage({ orders, customers, products, priceTables, customerMonitoring, openTab }) {
  const pendingOrders = orders.filter(isOrderInApproval);
  const overdueDeliveries = orders.filter(isOrderDeliveryOverdue);
  const approvedOrders = orders.filter((order) => order.status === "approved");
  const criticalCustomers = customerMonitoring.filter((row) => row.health_status === "critical");
  const openOrderTotal = orders
    .filter((order) => !["cancelled", "rejected"].includes(order.status))
    .reduce((total, order) => total + Number(order.total_amount || 0), 0);
  const recentOrders = orders.slice(0, 5);

  return (
    <div className="home-layout">
      <section className="home-hero">
        <div>
          <p>EasySales</p>
          <h2>Operacao comercial em tempo real</h2>
          <span>Pedidos, autorizacoes, entregas e carteira de clientes no mesmo lugar.</span>
        </div>
        <div className="home-actions">
          <button className="primary-button" onClick={() => openTab("orders")}><ClipboardList size={17} /> Pedidos</button>
          <button className="secondary-button" onClick={() => openTab("approvals")}><CheckCircle2 size={17} /> Autorizar</button>
        </div>
      </section>

      <section className="home-kpis">
        <HomeCard label="Pedidos em autorizacao" value={pendingOrders.length} tone="warning" onClick={() => openTab("approvals")} />
        <HomeCard label="Entregas vencidas" value={overdueDeliveries.length} tone="danger" onClick={() => openTab("orders")} />
        <HomeCard label="Clientes criticos" value={criticalCustomers.length} tone="danger" onClick={() => openTab("customerManagement")} />
        <HomeCard label="Carteira aberta" value={money.format(openOrderTotal)} tone="success" onClick={() => openTab("orders")} />
      </section>

      <section className="home-grid">
        <article className="home-panel">
          <div className="panel-header compact">
            <div>
              <p>Operacoes</p>
              <h2>Pedidos recentes</h2>
            </div>
          </div>
          <div className="home-list">
            {recentOrders.map((order) => (
              <button key={order.id} type="button" onClick={() => openTab("orders")}>
                <span>
                  <strong>{order.order_number}</strong>
                  <small>{order.customer_name}</small>
                </span>
                <OrderStatus status={order.status} overdue={isOrderDeliveryOverdue(order)} />
              </button>
            ))}
            {recentOrders.length === 0 && <div className="empty-detail">Nenhum pedido cadastrado.</div>}
          </div>
        </article>

        <article className="home-panel">
          <div className="panel-header compact">
            <div>
              <p>Cadastros</p>
              <h2>Base comercial</h2>
            </div>
          </div>
          <div className="home-base">
            <span><strong>{customers.length}</strong> clientes</span>
            <span><strong>{products.length}</strong> produtos</span>
            <span><strong>{priceTables.length}</strong> tabelas</span>
            <span><strong>{approvedOrders.length}</strong> pedidos autorizados</span>
          </div>
        </article>
      </section>
    </div>
  );
}

function HomeCard({ label, value, tone, onClick }) {
  return (
    <button type="button" className={`home-card ${tone}`} onClick={onClick}>
      <span>{label}</span>
      <strong>{value}</strong>
    </button>
  );
}

function lotTypeLabel(value) {
  return ({ seeds: "Sementes", general: "Geral", none: "Nao controla" }[value] || value || "Nao controla");
}

function ProductsBrowser({ products, groups, classes, warehouses, balances, movements, companies, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(products, ["sku", "name", "product_group_name", "product_class_name"], "products");
  const rows = browser.rows;

  function toForm(item) {
    return item ? { product_group_id: item.product_group_id || "", product_class_id: item.product_class_id || "", sku: item.sku, name: item.name, unit: item.unit, purchase_price: String(item.purchase_price || "0.00"), cost_price: String(item.cost_price || "0.00"), suggested_margin_percent: String(item.suggested_margin_percent || "0.00"), sale_price: String(item.sale_price || "0.00"), default_warehouse_id: item.default_warehouse_id || "", description: item.description || "", active: item.active } : emptyProduct;
  }

  async function save(form, item) {
    const payload = {
      product_group_id: form.product_group_id ? Number(form.product_group_id) : null,
      product_class_id: form.product_class_id ? Number(form.product_class_id) : null,
      sku: form.sku.trim().toUpperCase(),
      name: form.name.trim(),
      unit: form.unit.trim().toUpperCase() || "UN",
      purchase_price: Number(form.purchase_price || 0),
      cost_price: Number(form.cost_price || 0),
      suggested_margin_percent: Number(form.suggested_margin_percent || 0),
      sale_price: Number(suggestedProductPrice(form.cost_price, form.suggested_margin_percent) || 0),
      default_warehouse_id: form.default_warehouse_id ? Number(form.default_warehouse_id) : null,
      description: form.description.trim() || null,
      active: form.active,
    };
    await run(() => item ? api.put(`/products/${item.id}`, payload) : api.post("/products", payload));
    setModal(null);
  }

  return (
    <Browser title="Produtos" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["SKU", "Produto", "Grupo", "Local padrao", "Lote", "Ult. compra", "Custo", "Margem", "Preco sugerido", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        item.sku,
        item.name,
        item.product_group_name || "-",
        item.default_warehouse_name || "-",
        item.controls_lot ? lotTypeLabel(item.lot_type) : "Nao controla",
        money.format(Number(item.purchase_price || 0)),
        money.format(Number(item.cost_price || 0)),
        `${decimal.format(Number(item.suggested_margin_percent || 0))}%`,
        money.format(Number(item.sale_price || 0)),
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/products/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/products/${item.id}`))} />} />
      {modal && <ProductModal state={modal} setState={setModal} groups={groups} classes={classes} warehouses={warehouses} balances={balances} movements={movements} companies={companies} run={run} onSave={save} />}
    </Browser>
  );
}

function ProductModal({ state, setState, groups, classes, warehouses, balances, movements, companies, run, onSave }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const [lotConfig, setLotConfig] = useState({ controls_lot: item?.controls_lot || false, lot_type: item?.lot_type || "none" });
  const [companyIds, setCompanyIds] = useState(item?.company_ids || []);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  const productBalances = item ? balances.filter((row) => String(row.product_external_id) === String(item.id)) : [];
  const productMovements = item ? movements.filter((row) => String(row.product_external_id) === String(item.id)) : [];
  const suggestedPrice = suggestedProductPrice(form.cost_price, form.suggested_margin_percent);

  async function saveLotConfig() {
    if (!item?.id) return;
    const response = await run(() => api.put(`/products/${item.id}/lot-config`, lotConfig));
    if (response) setState({ ...state, item: response.data });
  }

  async function submit() {
    if (activeTab === "companies" && item) {
      const response = await run(() => api.put(`/products/${item.id}/companies`, { company_ids: companyIds }));
      if (response) setState(null);
      return;
    }
    await onSave(form, item);
  }

  return (
    <Modal title={item ? "Editar produto" : "Novo produto"} onClose={() => setState(null)} onSubmit={submit}>
      <div className="tabs">
        <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
        <button type="button" className={activeTab === "companies" ? "active" : ""} onClick={() => setActiveTab("companies")} disabled={!item}>Estabelecimentos</button>
        <button type="button" className={activeTab === "stock" ? "active" : ""} onClick={() => setActiveTab("stock")} disabled={!item}>Saldo</button>
      </div>

      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="SKU"><input required value={form.sku} onChange={(e) => update("sku", e.target.value.toUpperCase())} /></Field>
          <Field label="Produto"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="Grupo"><Select value={form.product_group_id} onChange={(v) => update("product_group_id", v)} options={groups} empty="Sem grupo" /></Field>
          <Field label="Classe"><Select value={form.product_class_id} onChange={(v) => update("product_class_id", v)} options={classes} empty="Sem classe" /></Field>
          <Field label="Local padrao"><Select value={form.default_warehouse_id} onChange={(v) => update("default_warehouse_id", v)} options={warehouses} empty="Sem local padrao" /></Field>
          <Field label="Unidade"><input value={form.unit} onChange={(e) => update("unit", e.target.value.toUpperCase())} /></Field>
          <Field label="Ult. compra"><input type="number" min="0" step="0.01" value={form.purchase_price} disabled /></Field>
          <Field label="Custo"><input type="number" min="0" step="0.01" value={form.cost_price} disabled /></Field>
          <Field label="Margem sugerida (%)"><input type="number" min="0" step="0.01" value={form.suggested_margin_percent} onChange={(e) => update("suggested_margin_percent", e.target.value)} /></Field>
          <Field label="Preco sugerido"><input type="number" min="0" step="0.01" value={suggestedPrice} disabled /></Field>
          <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
          <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
          {item && (
            <div className="lot-config-row span-2">
              <Check label="Controla lote" checked={lotConfig.controls_lot} onChange={(value) => setLotConfig({ ...lotConfig, controls_lot: value, lot_type: value ? (lotConfig.lot_type === "none" ? "general" : lotConfig.lot_type) : "none" })} />
              <Field label="Tipo de lote">
                <select value={lotConfig.lot_type} disabled={!lotConfig.controls_lot} onChange={(event) => setLotConfig({ ...lotConfig, lot_type: event.target.value })}>
                  <option value="none">Nao controla</option>
                  <option value="seeds">Sementes</option>
                  <option value="general">Geral</option>
                </select>
              </Field>
              <button type="button" className="secondary-button" onClick={saveLotConfig}>Salvar lote</button>
            </div>
          )}
        </div>
      )}

      {activeTab === "stock" && item && (
        <div className="detail-stack">
          <section className="subpanel">
            <div className="panel-header">
              <div>
                <p>Guia de saldo</p>
                <h2>Saldos por local</h2>
              </div>
            </div>
            <DataTable columns={["Local", "Saldo", "Quantidade"]} rows={productBalances.map((row) => [
              row.warehouse_name || "-",
              `${row.balance_code} - ${row.balance_name}`,
              decimal.format(Number(row.balance_quantity || 0)),
            ])} />
          </section>
          <details className="subpanel" open>
            <summary>Movimentacoes do produto</summary>
            <DataTable columns={["Data mov.", "Documento", "Operacao", "Local", "Quantidade", "Valor unit."]} rows={productMovements.slice(0, 80).map((row) => [
              row.movement_date || new Date(row.created_at).toLocaleDateString("pt-BR"),
              row.document_type_code ? `${row.document_type_code}${row.document_number ? ` ${row.document_number}` : ""}` : "-",
              row.operation_code ? `${row.operation_code} - ${row.operation_name}` : "-",
              row.warehouse_name || "-",
              decimal.format(Number(row.quantity || 0)),
              money.format(Number(row.unit_price || 0)),
            ])} />
          </details>
        </div>
      )}
      {activeTab === "companies" && item && (
        <CompanyLinksEditor
          companies={companies}
          linkedIds={item.company_ids || []}
          onChange={setCompanyIds}
        />
      )}
    </Modal>
  );
}

function PriceTablesBrowser({ priceTables, products, companies, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(priceTables, ["code", "name", "correction_mode"], "price_tables");
  const rows = browser.rows;

  function toForm(item) {
    return item ? { code: item.code, name: item.name, correction_mode: item.correction_mode, monthly_rate: String(item.monthly_rate || "0.00"), base_date: item.base_date, active: item.active } : emptyPriceTable;
  }

  async function save(form, item) {
    const payload = { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(), monthly_rate: Number(form.monthly_rate || 0) };
    await run(() => item ? api.put(`/price-tables/${item.id}`, payload) : api.post("/price-tables", payload));
    setModal(null);
  }

  return (
    <Browser title="Tabelas de preco" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Codigo", "Nome", "Correcao", "Taxa mensal", "Data base", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        item.code,
        item.name,
        item.correction_mode === "inside" ? "Por dentro" : "Por fora",
        `${Number(item.monthly_rate || 0).toLocaleString("pt-BR")}%`,
        item.base_date,
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/price-tables/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/price-tables/${item.id}`))} />} />

      {modal && <PriceTableModal state={modal} setState={setModal} products={products} companies={companies} run={run} onSave={save} />}
    </Browser>
  );
}

function PriceTableModal({ state, setState, products, companies, run, onSave }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const [companyIds, setCompanyIds] = useState(item?.company_ids || []);
  const [items, setItems] = useState([]);
  const [itemForm, setItemForm] = useState(emptyPriceItem);
  const [editingItem, setEditingItem] = useState(null);
  const [tiers, setTiers] = useState([]);
  const [tierForm, setTierForm] = useState(emptyPriceTier);
  const [editingTier, setEditingTier] = useState(null);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });

  useEffect(() => {
    if (item?.id) loadItems();
  }, [item?.id]);

  async function loadItems() {
    const response = await api.get(`/price-tables/${item.id}/items`);
    setItems(response.data);
  }

  async function loadTiers(priceItemId) {
    const response = await api.get(`/price-table-items/${priceItemId}/tiers`);
    setTiers(response.data);
  }

  async function saveItem() {
    if (!item?.id || !itemForm.product_id) return;
    const payload = {
      product_id: Number(itemForm.product_id),
      base_price: Number(itemForm.base_price || 0),
      margin_percent: Number(itemForm.margin_percent || 0),
      active: itemForm.active,
    };
    await run(() => editingItem ? api.put(`/price-table-items/${editingItem.id}`, payload) : api.post(`/price-tables/${item.id}/items`, payload));
    setEditingItem(null);
    setItemForm(emptyPriceItem);
    setTiers([]);
    setEditingTier(null);
    setTierForm(emptyPriceTier);
    await loadItems();
  }

  async function removeItem(priceItem) {
    await run(() => api.delete(`/price-table-items/${priceItem.id}`));
    await loadItems();
  }

  function editItem(priceItem) {
    setEditingItem(priceItem);
    setTiers(priceItem.tiers || []);
    setEditingTier(null);
    setTierForm(emptyPriceTier);
    setItemForm({
      product_id: priceItem.product_id || "",
      base_price: String(priceItem.base_price || "0.00"),
      margin_percent: String(priceItem.margin_percent || "5.00"),
      active: priceItem.active,
    });
  }

  function cancelItemEdit() {
    setEditingItem(null);
    setItemForm(emptyPriceItem);
    setTiers([]);
    setEditingTier(null);
    setTierForm(emptyPriceTier);
  }

  async function saveTier() {
    if (!editingItem?.id) return;
    const payload = {
      min_quantity: Number(tierForm.min_quantity || 0),
      discount_percent: Number(tierForm.discount_percent || 0),
      active: tierForm.active,
    };
    await run(() => editingTier ? api.put(`/price-table-item-tiers/${editingTier.id}`, payload) : api.post(`/price-table-items/${editingItem.id}/tiers`, payload));
    setEditingTier(null);
    setTierForm(emptyPriceTier);
    await loadTiers(editingItem.id);
    await loadItems();
  }

  async function removeTier(tier) {
    await run(() => api.delete(`/price-table-item-tiers/${tier.id}`));
    await loadTiers(editingItem.id);
    await loadItems();
  }

  function editTier(tier) {
    setEditingTier(tier);
    setTierForm({
      min_quantity: String(tier.min_quantity || "1.00"),
      discount_percent: String(tier.discount_percent || "0.00"),
      active: tier.active,
    });
  }

  async function submit() {
    if (activeTab === "companies" && item) {
      const response = await run(() => api.put(`/price-tables/${item.id}/companies`, { company_ids: companyIds }));
      if (response) setState(null);
      return;
    }
    await onSave(form, item);
  }

  return (
    <Modal title={item ? "Editar tabela de preco" : "Nova tabela de preco"} onClose={() => setState(null)} onSubmit={submit}>
      <div className="tabs">
        <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
        <button type="button" className={activeTab === "items" ? "active" : ""} onClick={() => setActiveTab("items")} disabled={!item}>Itens</button>
        <button type="button" className={activeTab === "companies" ? "active" : ""} onClick={() => setActiveTab("companies")} disabled={!item}>Estabelecimentos</button>
      </div>

      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
          <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="Correcao"><select value={form.correction_mode} onChange={(e) => update("correction_mode", e.target.value)}><option value="outside">Por fora</option><option value="inside">Por dentro</option></select></Field>
          <Field label="Taxa mensal %"><input type="number" step="0.0001" value={form.monthly_rate} onChange={(e) => update("monthly_rate", e.target.value)} /></Field>
          <Field label="Data base"><input type="date" value={form.base_date} onChange={(e) => update("base_date", e.target.value)} /></Field>
          <Check label="Ativa" checked={form.active} onChange={(v) => update("active", v)} />
        </div>
      )}

      {activeTab === "items" && (
        <section className="modal-detail">
          <div className="panel-header">
            <div>
              <p>Itens da tabela</p>
              <h2>Produtos e precos</h2>
            </div>
          </div>

          {!item?.id && <div className="empty-detail">Salve o cabecalho da tabela para incluir produtos.</div>}

          {item?.id && (
            <>
            <div className="detail-form">
              <Field label="Produto" wide><Select value={itemForm.product_id} onChange={(v) => setItemForm({ ...itemForm, product_id: v })} options={products} empty="Selecione" /></Field>
              <Field label="Preco base"><input type="number" min="0" step="0.01" value={itemForm.base_price} onChange={(e) => setItemForm({ ...itemForm, base_price: e.target.value })} /></Field>
              <Field label="Margem %"><input type="number" min="0" step="0.01" value={itemForm.margin_percent} onChange={(e) => setItemForm({ ...itemForm, margin_percent: e.target.value })} /></Field>
              <Check label="Ativo" checked={itemForm.active} onChange={(v) => setItemForm({ ...itemForm, active: v })} />
              <div className="form-actions">
                {editingItem && <button type="button" className="secondary-button" onClick={cancelItemEdit}>Cancelar item</button>}
                <button type="button" className="primary-button" onClick={saveItem}>{editingItem ? "Salvar item" : "Incluir item"}</button>
              </div>
            </div>

            <DataTable columns={["Produto", "Preco base", "Margem", "Progressiva", "Status", "Acoes"]} rows={items.map((priceItem) => [
              `${priceItem.product_sku || ""} ${priceItem.product_name || ""}`.trim(),
              money.format(Number(priceItem.base_price || 0)),
              `${percent.format(Number(priceItem.margin_percent || 0))}%`,
              `${priceItem.tiers?.length || 0} faixa(s)`,
              <Status active={priceItem.active} />,
              <RowActions onEdit={() => editItem(priceItem)} onRemove={() => removeItem(priceItem)} />,
            ])} />

            {editingItem && (
              <section className="nested-detail">
                <div className="panel-header compact">
                  <div>
                    <p>Politica progressiva</p>
                    <h2>{editingItem.product_name}</h2>
                  </div>
                </div>
                <div className="tier-form">
                  <Field label="Qtd. minima"><input type="number" min="0.0001" step="0.0001" value={tierForm.min_quantity} onChange={(e) => setTierForm({ ...tierForm, min_quantity: e.target.value })} /></Field>
                  <Field label="Desconto %"><input type="number" min="0" max="99.9999" step="0.01" value={tierForm.discount_percent} onChange={(e) => setTierForm({ ...tierForm, discount_percent: e.target.value })} /></Field>
                  <Check label="Ativa" checked={tierForm.active} onChange={(v) => setTierForm({ ...tierForm, active: v })} />
                  <div className="form-actions">
                    {editingTier && <button type="button" className="secondary-button" onClick={() => { setEditingTier(null); setTierForm(emptyPriceTier); }}>Cancelar faixa</button>}
                    <button type="button" className="primary-button" onClick={saveTier}>{editingTier ? "Salvar faixa" : "Incluir faixa"}</button>
                  </div>
                </div>
                <DataTable columns={["Qtd. minima", "Desconto", "Status", "Acoes"]} rows={tiers.map((tier) => [
                  decimal.format(Number(tier.min_quantity || 0)),
                  `${percent.format(Number(tier.discount_percent || 0))}%`,
                  <Status active={tier.active} />,
                  <RowActions onEdit={() => editTier(tier)} onRemove={() => removeTier(tier)} />,
                ])} />
              </section>
            )}
            </>
          )}
        </section>
      )}

      {activeTab === "companies" && item && (
        <CompanyLinksEditor
          companies={companies}
          linkedIds={item.company_ids || []}
          onChange={setCompanyIds}
        />
      )}
    </Modal>
  );
}

function SimpleCatalogBrowser({ title, eyebrow, endpoint, entityCode, items, template, run, companies = [], companyEndpoint = null }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(items, ["code", "name", "description"], entityCode);
  const rows = browser.rows;

  async function save(form, item) {
    const payload = { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description.trim() || null };
    await run(() => item ? api.put(`${endpoint}/${item.id}`, payload) : api.post(endpoint, payload));
    setModal(null);
  }

  return (
    <Browser title={title} eyebrow={eyebrow} {...browser} onNew={() => setModal({ item: null, form: template })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Codigo", "Nome", "Descricao", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        item.code,
        item.name,
        item.description || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: { code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`${endpoint}/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: { code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`${endpoint}/${item.id}`))} />} />
      {modal && <SimpleCatalogModal title={title} state={modal} setState={setModal} onSave={save} companies={companies} companyEndpoint={companyEndpoint} run={run} />}
    </Browser>
  );
}

function SimpleCatalogModal({ title, state, setState, onSave, companies = [], companyEndpoint = null, run }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const [companyIds, setCompanyIds] = useState(item?.company_ids || []);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });

  async function submit() {
    if (companyEndpoint && activeTab === "companies" && item) {
      const response = await run(() => api.put(`${companyEndpoint}/${item.id}/companies`, { company_ids: companyIds }));
      if (response) setState(null);
      return;
    }
    await onSave(form, item);
  }

  return (
    <Modal title={item ? `Editar ${title.toLowerCase()}` : title} onClose={() => setState(null)} onSubmit={submit}>
      {companyEndpoint && (
        <div className="tabs">
          <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
          <button type="button" className={activeTab === "companies" ? "active" : ""} onClick={() => setActiveTab("companies")} disabled={!item}>Estabelecimentos</button>
        </div>
      )}

      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
          <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
          <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
        </div>
      )}

      {companyEndpoint && activeTab === "companies" && item && (
        <CompanyLinksEditor
          companies={companies}
          linkedIds={item.company_ids || []}
          onChange={setCompanyIds}
        />
      )}
    </Modal>
  );
}

function ClassesBrowser({ classes, groups, companies, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(classes, ["code", "name", "product_group_name", "description"], "product_classes");
  const rows = browser.rows;

  async function save(form, item) {
    const payload = { ...form, product_group_id: form.product_group_id ? Number(form.product_group_id) : null, code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description.trim() || null };
    await run(() => item ? api.put(`/product-classes/${item.id}`, payload) : api.post("/product-classes", payload));
    setModal(null);
  }

  return (
    <Browser title="Classes de produtos" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: emptyClass })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Codigo", "Nome", "Grupo", "Descricao", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        item.code,
        item.name,
        item.product_group_name || "-",
        item.description || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: { product_group_id: item.product_group_id || "", code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`/product-classes/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: { product_group_id: item.product_group_id || "", code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`/product-classes/${item.id}`))} />} />
      {modal && <ClassModal state={modal} setState={setModal} groups={groups} companies={companies} run={run} onSave={save} />}
    </Browser>
  );
}

function ClassModal({ state, setState, groups, companies, run, onSave }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const [companyIds, setCompanyIds] = useState(item?.company_ids || []);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });

  async function submit() {
    if (activeTab === "companies" && item) {
      const response = await run(() => api.put(`/product-classes/${item.id}/companies`, { company_ids: companyIds }));
      if (response) setState(null);
      return;
    }
    await onSave(form, item);
  }

  return (
    <Modal title={item ? "Editar classe" : "Nova classe"} onClose={() => setState(null)} onSubmit={submit}>
      <div className="tabs">
        <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
        <button type="button" className={activeTab === "companies" ? "active" : ""} onClick={() => setActiveTab("companies")} disabled={!item}>Estabelecimentos</button>
      </div>

      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
          <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="Grupo" wide><Select value={form.product_group_id} onChange={(v) => update("product_group_id", v)} options={groups} empty="Sem grupo" /></Field>
          <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
          <Check label="Ativa" checked={form.active} onChange={(v) => update("active", v)} />
        </div>
      )}

      {activeTab === "companies" && item && (
        <CompanyLinksEditor
          companies={companies}
          linkedIds={item.company_ids || []}
          onChange={setCompanyIds}
        />
      )}
    </Modal>
  );
}

function CustomerProfilesBrowser({ profiles, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(profiles, ["code", "name", "description"], "customer_profiles");
  const rows = browser.rows;

  function toForm(item) {
    return item ? {
      code: item.code,
      name: item.name,
      description: item.description || "",
      max_inactive_days: String(item.max_inactive_days || 0),
      max_overdue_days: String(item.max_overdue_days || 0),
      block_without_movement: item.block_without_movement,
      block_overdue_titles: item.block_overdue_titles,
      active: item.active,
      payment_rules: (item.payment_rules || []).map((rule) => ({
        payment_method: rule.payment_method || "avista",
        max_installments: String(rule.max_installments || 1),
        max_total_days: String(rule.max_total_days || 0),
        active: rule.active,
      })),
    } : emptyCustomerProfile;
  }

  async function save(form, item) {
    const payload = {
      code: form.code.trim().toUpperCase(),
      name: form.name.trim(),
      description: form.description.trim() || null,
      max_inactive_days: Number(form.max_inactive_days || 0),
      max_overdue_days: Number(form.max_overdue_days || 0),
      block_without_movement: form.block_without_movement,
      block_overdue_titles: form.block_overdue_titles,
      active: form.active,
      payment_rules: (form.payment_rules || []).map((rule) => ({
        payment_method: rule.payment_method,
        max_installments: Number(rule.max_installments || 1),
        max_total_days: Number(rule.max_total_days || 0),
        active: rule.active,
      })),
    };
    await run(() => item ? api.put(`/customer-profiles/${item.id}`, payload) : api.post("/customer-profiles", payload));
    setModal(null);
  }

  return (
    <Browser title="Perfis comerciais" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Codigo", "Nome", "Dias sem mov.", "Titulos vencidos", "Cond. pgto.", "Bloqueios", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        item.code,
        item.name,
        item.max_inactive_days,
        item.max_overdue_days,
        (item.payment_rules || []).filter((rule) => rule.active).length || "Nenhuma",
        [item.block_without_movement && "Sem mov.", item.block_overdue_titles && "Vencidos"].filter(Boolean).join(" / ") || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/customer-profiles/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/customer-profiles/${item.id}`))} />} />
      {modal && <CustomerProfileModal state={modal} setState={setModal} onSave={save} />}
    </Browser>
  );
}

function CustomerProfileModal({ state, setState, onSave }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  const paymentRules = form.payment_rules || [];
  const updateRule = (index, field, value) => update("payment_rules", paymentRules.map((rule, rowIndex) => rowIndex === index ? { ...rule, [field]: value } : rule));
  const addRule = () => update("payment_rules", [...paymentRules, emptyProfilePaymentRule]);
  const removeRule = (index) => update("payment_rules", paymentRules.filter((_, rowIndex) => rowIndex !== index));
  return (
    <Modal title={item ? "Editar perfil comercial" : "Novo perfil comercial"} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="modal-grid">
        <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
        <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="Dias sem movimentacao"><input type="number" min="0" value={form.max_inactive_days} onChange={(e) => update("max_inactive_days", e.target.value)} /></Field>
        <Field label="Titulos vencidos acima de"><input type="number" min="0" value={form.max_overdue_days} onChange={(e) => update("max_overdue_days", e.target.value)} /></Field>
        <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
        <Check label="Bloquear sem movimentacao" checked={form.block_without_movement} onChange={(v) => update("block_without_movement", v)} />
        <Check label="Bloquear por titulos vencidos" checked={form.block_overdue_titles} onChange={(v) => update("block_overdue_titles", v)} />
        <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
      </div>
      <section className="nested-detail">
        <div className="panel-header compact">
          <div>
            <p>Aprovacao financeira</p>
            <h3>Condicoes de pagamento liberadas</h3>
          </div>
          <button type="button" className="secondary-button" onClick={addRule}>Adicionar regra</button>
        </div>
        <div className="source-hint">Sem regras ativas, toda condicao de pagamento cai para autorizacao financeira.</div>
        <DataTable columns={["Condicao", "Parcelas max.", "Dias max.", "Ativa", "Acoes"]} rows={paymentRules.map((rule, index) => [
          <select value={rule.payment_method} onChange={(event) => updateRule(index, "payment_method", event.target.value)}>
            <option value="avista">A vista</option>
            <option value="parcelado">Parcelado</option>
            <option value="adiantamento">Adiantamento</option>
          </select>,
          <input type="number" min="1" step="1" value={rule.max_installments} onChange={(event) => updateRule(index, "max_installments", event.target.value)} />,
          <input type="number" min="0" step="1" value={rule.max_total_days} onChange={(event) => updateRule(index, "max_total_days", event.target.value)} />,
          <Check label="Ativa" checked={rule.active} onChange={(value) => updateRule(index, "active", value)} />,
          <button type="button" className="secondary-button compact-button" onClick={() => removeRule(index)}>Remover</button>,
        ])} />
      </section>
    </Modal>
  );
}

function SalesRepresentativesBrowser({ representatives, users, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(representatives, ["user_name", "user_email", "code", "whatsapp_number"], "sales_representatives");
  const rows = browser.rows;

  function toForm(item) {
    return item ? {
      user_id: item.user_id || "",
      code: item.code || "",
      whatsapp_number: item.whatsapp_number || "",
      active: item.active,
    } : { ...emptySalesRepresentative };
  }

  async function save(form, item) {
    const payload = {
      user_id: Number(form.user_id),
      code: form.code.trim() || null,
      whatsapp_number: form.whatsapp_number.trim(),
      active: form.active,
    };
    const saved = await run(() => item
      ? api.put(`/sales-representatives/${item.id}`, payload)
      : api.post("/sales-representatives", payload));
    if (saved) setModal(null);
  }

  return (
    <Browser title="Vendedores" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Vendedor", "Codigo", "WhatsApp", "Clientes", "Status", "Acoes"]} fallbackRows={rows.map((item) => [
        <span><strong>{item.user_name}</strong><small className="muted-inline">{item.user_email}</small></span>,
        item.code || "-",
        item.whatsapp_number,
        item.customer_count,
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/sales-representatives/${item.id}`))} />,
      ])} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/sales-representatives/${item.id}`))} />} />
      {modal && (
        <SalesRepresentativeModal
          state={modal}
          setState={setModal}
          users={users}
          onSave={save}
        />
      )}
    </Browser>
  );
}

function SalesRepresentativeModal({ state, setState, users, onSave }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });

  return (
    <Modal title={item ? "Editar vendedor" : "Novo vendedor"} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="tabs">
        <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
        <button type="button" className={activeTab === "portfolio" ? "active" : ""} onClick={() => setActiveTab("portfolio")} disabled={!item}>Carteira</button>
      </div>
      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="Usuario" wide><Select required value={form.user_id} onChange={(value) => update("user_id", value)} options={users} empty="Selecione" labelKey="name" /></Field>
          <Field label="Codigo"><input value={form.code} onChange={(event) => update("code", event.target.value.toUpperCase())} /></Field>
          <Field label="WhatsApp"><input required inputMode="tel" placeholder="5546999999999" value={form.whatsapp_number} onChange={(event) => update("whatsapp_number", event.target.value)} /></Field>
          <Check label="Vendedor ativo" checked={form.active} onChange={(value) => update("active", value)} />
        </div>
      )}
      {activeTab === "portfolio" && (
        <SalesRepresentativePortfolio representative={item} />
      )}
    </Modal>
  );
}

function SalesRepresentativePortfolio({ representative }) {
  const [search, setSearch] = useState("");
  const [available, setAvailable] = useState([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState("");
  const [searching, setSearching] = useState(false);
  const [portfolioQuery, setPortfolioQuery] = useState("");
  const [portfolio, setPortfolio] = useState({ items: [], page: 1, total: 0, total_pages: 1 });
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const [message, setMessage] = useState("");

  async function loadPortfolio(page = 1, query = portfolioQuery) {
    setLoadingPortfolio(true);
    try {
      const response = await api.get(`/sales-representatives/${representative.id}/customers`, {
        params: { page, page_size: 30, query },
      });
      setPortfolio(response.data);
    } catch (error) {
      setMessage(error?.response?.data?.detail || "Nao foi possivel carregar a carteira.");
    } finally {
      setLoadingPortfolio(false);
    }
  }

  useEffect(() => {
    const term = search.trim();
    setSelectedCustomerId("");
    if (term.length < 2) {
      setAvailable([]);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.get("/sales-representatives/customer-options", {
          params: { query: term, page: 1, page_size: 20 },
        });
        setAvailable(response.data.items);
      } catch (error) {
        setMessage(error?.response?.data?.detail || "Nao foi possivel pesquisar clientes.");
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search, representative.id]);

  useEffect(() => {
    const timer = window.setTimeout(() => loadPortfolio(1, portfolioQuery), 300);
    return () => window.clearTimeout(timer);
  }, [portfolioQuery, representative.id]);

  async function addCustomer() {
    if (!selectedCustomerId) return;
    try {
      await api.post(`/sales-representatives/${representative.id}/customers`, {
        customer_id: selectedCustomerId,
      });
      setSearch("");
      setAvailable([]);
      setSelectedCustomerId("");
      setMessage("Cliente adicionado a carteira.");
      await loadPortfolio(1, portfolioQuery);
    } catch (error) {
      setMessage(error?.response?.data?.detail || "Nao foi possivel adicionar o cliente.");
    }
  }

  async function removeCustomer(row) {
    try {
      await api.delete(
        `/sales-representatives/${representative.id}/customers/${row.customer_source}/${row.customer_external_id}`,
      );
      setMessage("Vinculo removido.");
      const targetPage = portfolio.items.length === 1 && portfolio.page > 1 ? portfolio.page - 1 : portfolio.page;
      await loadPortfolio(targetPage, portfolioQuery);
    } catch (error) {
      setMessage(error?.response?.data?.detail || "Nao foi possivel remover o vinculo.");
    }
  }

  return (
    <div className="portfolio-editor">
      <section className="portfolio-add">
        <div className="panel-header compact">
          <div>
            <p>Adicionar cliente</p>
            <h3>Pesquisar cadastro</h3>
          </div>
        </div>
        <div className="portfolio-add-controls">
          <Field label="Busca">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Codigo, nome, documento ou cidade"
            />
          </Field>
          <Field label="Cliente">
            <select
              value={selectedCustomerId}
              disabled={search.trim().length < 2 || searching}
              onChange={(event) => setSelectedCustomerId(event.target.value)}
            >
              <option value="">{searching ? "Pesquisando..." : "Selecione um resultado"}</option>
              {available.map((customer) => (
                <option value={customer.customer_id} key={customer.customer_id}>
                  {customer.customer_code} - {customer.customer_name}
                </option>
              ))}
            </select>
          </Field>
          <button type="button" className="primary-button" disabled={!selectedCustomerId} onClick={addCustomer}>
            <Plus size={16} /> Adicionar
          </button>
        </div>
      </section>

      <section className="portfolio-links">
        <div className="panel-header compact">
          <div>
            <p>Vinculos ativos</p>
            <h3>Carteira do vendedor</h3>
          </div>
          <input
            value={portfolioQuery}
            onChange={(event) => setPortfolioQuery(event.target.value)}
            placeholder="Filtrar carteira..."
          />
        </div>
        {message && <div className="source-hint">{message}</div>}
        <DataTable columns={["Cod. vendedor", "Cod. cliente", "Cliente", "Documento", "Cidade/UF", "Acoes"]} rows={portfolio.items.map((row) => [
          row.sales_representative_code || `VD-${String(row.sales_representative_id).padStart(6, "0")}`,
          row.customer_code,
          row.customer_name,
          row.document_number || "-",
          [row.city, row.state_code].filter(Boolean).join(" / ") || "-",
          <button type="button" className="icon-button" title="Remover da carteira" onClick={() => removeCustomer(row)}>
            <Trash2 size={15} />
          </button>,
        ])} />
        {loadingPortfolio && <div className="empty-detail">Carregando carteira...</div>}
        {!loadingPortfolio && portfolio.items.length === 0 && <div className="empty-detail">Nenhum cliente vinculado.</div>}
        <div className="portfolio-pagination">
          <span>{portfolio.total} cliente(s) | Pagina {portfolio.page}/{portfolio.total_pages}</span>
          <div>
            <button type="button" className="secondary-button" disabled={portfolio.page <= 1 || loadingPortfolio} onClick={() => loadPortfolio(portfolio.page - 1)}>Anterior</button>
            <button type="button" className="secondary-button" disabled={portfolio.page >= portfolio.total_pages || loadingPortfolio} onClick={() => loadPortfolio(portfolio.page + 1)}>Proxima</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function CustomersBrowser({ customers, customerProfiles, salesRepresentatives, companies, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(customers, ["name", "document_number", "email", "phone", "city", "customer_profile_name"], "customers");
  const rows = browser.rows;

  function localId(item) {
    return item.id?.startsWith("local:") ? item.id.replace("local:", "") : null;
  }

  async function save(form, item) {
    const payload = { ...form, customer_profile_id: form.customer_profile_id ? Number(form.customer_profile_id) : null, name: form.name.trim(), document_number: form.document_number || null, email: form.email || null, phone: form.phone || null, city: form.city || null, state_code: form.state_code || null };
    delete payload.sales_representative_id;
    const id = item ? localId(item) : null;
    const saved = await run(() => {
      if (!payload.customer_profile_id) throw new Error(MESSAGES.customers.profileRequired);
      return id ? api.put(`/customers/${id}`, payload) : api.post("/customers", payload);
    });
    if (!saved) return;
    const savedCustomer = saved.data;
    const [source, externalId] = (item?.id || savedCustomer?.id || "").split(":");
    if (source && externalId) {
      await run(() => api.put(`/customers/${source}/${externalId}/sales-representative`, {
        sales_representative_id: form.sales_representative_id ? Number(form.sales_representative_id) : null,
      }));
    }
    setModal(null);
  }

  return (
    <Browser title="Clientes" eyebrow="Cadastros" {...browser} onNew={() => setModal({ item: null, form: emptyCustomer })}>
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Cliente", "Documento", "Perfil", "Vendedor", "Limite", "Contato", "Cidade/UF", "Origem", "Status", "Acoes"]} fallbackRows={rows.map((item) => {
        const id = localId(item);
        return [
          item.name,
          item.document_number || "-",
          item.customer_profile_name || "-",
          item.sales_representative_name || "Sem responsavel",
          money.format(Number(item.credit_limit || 0)),
          item.email || item.phone || "-",
          [item.city, item.state_code].filter(Boolean).join(" / ") || "-",
          item.source,
          <Status active={item.active} />,
          id
            ? <RowActions onEdit={() => setModal({ item, form: { customer_profile_id: item.customer_profile_id || "", sales_representative_id: item.sales_representative_id || "", name: item.name, document_number: item.document_number || "", email: item.email || "", phone: item.phone || "", city: item.city || "", state_code: item.state_code || "", active: item.active } })} onRemove={() => run(() => api.delete(`/customers/${id}`))} />
            : <button type="button" className="link-button" onClick={() => setModal({ item, form: { customer_profile_id: item.customer_profile_id || "", sales_representative_id: item.sales_representative_id || "", name: item.name, document_number: item.document_number || "", email: item.email || "", phone: item.phone || "", city: item.city || "", state_code: item.state_code || "", active: item.active } })}>Perfil</button>,
        ];
      })} renderActions={(item) => {
        const id = localId(item);
        const form = { customer_profile_id: item.customer_profile_id || "", sales_representative_id: item.sales_representative_id || "", name: item.name, document_number: item.document_number || "", email: item.email || "", phone: item.phone || "", city: item.city || "", state_code: item.state_code || "", active: item.active };
        return id
          ? <RowActions onEdit={() => setModal({ item, form })} onRemove={() => run(() => api.delete(`/customers/${id}`))} />
          : <button type="button" className="link-button" onClick={() => setModal({ item, form })}>Perfil</button>;
      }} />
      {modal && <CustomerModal state={modal} setState={setModal} customerProfiles={customerProfiles} salesRepresentatives={salesRepresentatives} companies={companies} onSave={save} run={run} />}
    </Browser>
  );
}

function CustomerManagementPage({ rows, run }) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState({});
  const filtered = useMemo(() => filterRows(rows, query, ["customer_name", "current_profile_name", "suggested_profile_name", "health_status"]), [rows, query]);
  const summary = {
    critical: rows.filter((row) => row.health_status === "critical").length,
    attention: rows.filter((row) => row.health_status === "attention").length,
    healthy: rows.filter((row) => row.health_status === "healthy").length,
  };

  function applySuggestion(row) {
    const [source, externalId] = row.customer_id.split(":");
    return run(() => api.post(`/customer-monitoring/${source}/${externalId}/apply-suggested-profile`));
  }

  function toggle(customerId) {
    setExpanded((current) => ({ ...current, [customerId]: !current[customerId] }));
  }

  return (
    <section className="panel">
      <div className="browser-header">
        <div>
          <p>Operacoes</p>
          <h2>Gestao de clientes</h2>
        </div>
        <div className="browser-actions">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar cliente, perfil, status..." />
        </div>
      </div>
      <div className="health-summary">
        <span className="health-card critical"><strong>{summary.critical}</strong><small>Criticos</small></span>
        <span className="health-card attention"><strong>{summary.attention}</strong><small>Atencao</small></span>
        <span className="health-card healthy"><strong>{summary.healthy}</strong><small>Saudaveis</small></span>
      </div>
      <div className="customer-health-list">
        {filtered.map((row) => (
          <article className={`customer-health ${row.health_status}`} key={row.customer_id}>
            <header>
              <div>
                <strong>{row.customer_name}</strong>
                <span>{row.current_profile_name || "Sem perfil"} {"->"} {row.suggested_profile_name || "-"}</span>
              </div>
              <div className="customer-health-actions">
                <span className={`health-pill ${row.health_status}`}>{healthStatusLabel(row.health_status)}</span>
                <button type="button" className="link-button" onClick={() => toggle(row.customer_id)}>{expanded[row.customer_id] ? "Recolher" : "Detalhes"}</button>
              </div>
            </header>
            <div className="customer-health-metrics">
              <span><strong>{row.days_without_movement ?? "-"}</strong><small>dias sem mov.</small></span>
              <span><strong>{row.oldest_overdue_days}</strong><small>dias atraso</small></span>
              <span><strong>{row.alerts.length}</strong><small>alertas</small></span>
            </div>
            {row.suggested_profile_id && row.suggested_profile_id !== row.current_profile_id && (
              <button type="button" className="secondary-button compact-action" onClick={() => applySuggestion(row)}>Aplicar perfil {row.suggested_profile_name}</button>
            )}
            {expanded[row.customer_id] && (
              <div className="customer-alerts">
                {row.alerts.map((alert, index) => (
                  <div className={`customer-alert ${alert.severity}`} key={`${row.customer_id}-${index}`}>
                    <strong>{alert.segment === "financial" ? "Financeiro" : "Comercial"}</strong>
                    <span>{alert.message}</span>
                    {alert.suggested_action && <small>{alert.suggested_action}</small>}
                  </div>
                ))}
                {row.alerts.length === 0 && <div className="customer-alert healthy"><strong>Carteira em ordem</strong><span>Nenhum alerta para este cliente.</span></div>}
              </div>
            )}
          </article>
        ))}
        {filtered.length === 0 && <div className="empty-detail">Nenhum cliente encontrado.</div>}
      </div>
    </section>
  );
}

function OrderAssistantStatusPage({ status }) {
  if (!status) return <div className="empty-detail">Carregando assistente...</div>;
  return (
    <section className="panel">
      <div className="browser-header">
        <div>
          <p>Automacao comercial</p>
          <h2>Assistente de Pedidos via WhatsApp</h2>
        </div>
        <span className={`status-pill ${status.enabled ? "active" : "inactive"}`}>
          {status.enabled ? "Ativo" : "Inativo"}
        </span>
      </div>
      <div className="home-base">
        <span><strong>{status.provider}</strong> provedor</span>
        <span><strong>{status.model}</strong> modelo</span>
        <span><strong>{status.api_configured ? "Configurada" : "Pendente"}</strong> chave IA</span>
        <span><strong>{status.require_confirmation ? "Obrigatoria" : "Automatica"}</strong> confirmacao</span>
      </div>
      <div className="order-context">
        <span>Entrada Sales <strong>{status.sales_endpoint}</strong></span>
        <span>Webhook n8n <strong>{status.n8n_webhook || "-"}</strong></span>
        <span>Evolution <strong>{status.evolution_instance || "-"}</strong></span>
        <span>Prazo padrao <strong>{status.default_payment_days} dia(s)</strong></span>
      </div>
      <div className="panel-header compact">
        <div>
          <p>Operacao recente</p>
          <h3>Conversas processadas</h3>
        </div>
      </div>
      <DataTable columns={["Vendedor", "WhatsApp", "Estado", "Pedido", "Atualizado"]} rows={(status.sessions || []).map((row) => [
        row.sales_representative_name,
        row.whatsapp_number,
        row.state,
        row.order_number || "-",
        row.updated_at ? new Date(row.updated_at).toLocaleString("pt-BR") : "-",
      ])} />
    </section>
  );
}

function CustomerModal({ state, setState, customerProfiles, salesRepresentatives, companies, onSave, run }) {
  const { item, form } = state;
  const [activeTab, setActiveTab] = useState("data");
  const [companyIds, setCompanyIds] = useState(item?.company_ids || []);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  const isShared = item?.id?.startsWith("easyfinance:");
  async function saveSharedProfile() {
    const [source, externalId] = item.id.split(":");
    const saved = await run(() => {
      if (!form.customer_profile_id) throw new Error(MESSAGES.customers.profileRequired);
      return api.put(`/customers/${source}/${externalId}/profile`, { customer_profile_id: Number(form.customer_profile_id) });
    });
    if (saved) {
      await run(() => api.put(`/customers/${source}/${externalId}/sales-representative`, {
        sales_representative_id: form.sales_representative_id ? Number(form.sales_representative_id) : null,
      }));
      setState(null);
    }
  }

  async function submit() {
    if (activeTab === "companies" && item) {
      const [source, externalId] = item.id.split(":");
      const response = await run(() => api.put(`/customers/${source}/${externalId}/companies`, { company_ids: companyIds }));
      if (response) setState(null);
      return;
    }
    await (isShared ? saveSharedProfile() : onSave(form, item));
  }

  return (
    <Modal title={item ? "Editar cliente" : "Novo cliente"} onClose={() => setState(null)} onSubmit={submit}>
      <div className="tabs">
        <button type="button" className={activeTab === "data" ? "active" : ""} onClick={() => setActiveTab("data")}>Dados</button>
        <button type="button" className={activeTab === "companies" ? "active" : ""} onClick={() => setActiveTab("companies")} disabled={!item}>Estabelecimentos</button>
      </div>
      {activeTab === "data" && (
        <div className="modal-grid">
          <Field label="Nome" wide><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
          <Field label="CPF/CNPJ"><input value={form.document_number} onChange={(e) => update("document_number", e.target.value)} /></Field>
          <Field label="E-mail"><input value={form.email} onChange={(e) => update("email", e.target.value)} /></Field>
          <Field label="Telefone"><input value={form.phone} onChange={(e) => update("phone", e.target.value)} /></Field>
          <Field label="Cidade"><input value={form.city} onChange={(e) => update("city", e.target.value)} /></Field>
          <Field label="UF"><input maxLength="2" value={form.state_code} onChange={(e) => update("state_code", e.target.value.toUpperCase())} /></Field>
          <div className="form-section-title span-2">
            <span>Configuracao comercial</span>
          </div>
          <Field label="Perfil comercial"><Select required value={form.customer_profile_id} onChange={(v) => update("customer_profile_id", v)} options={customerProfiles} empty="Selecione" /></Field>
          <Field label="Vendedor responsavel"><Select value={form.sales_representative_id || ""} onChange={(v) => update("sales_representative_id", v)} options={salesRepresentatives.filter((representative) => representative.active)} empty="Sem responsavel" labelKey="user_name" /></Field>
          {isShared && <Field label="Limite de credito"><input disabled value={money.format(Number(item.credit_limit || 0))} /></Field>}
          <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
        </div>
      )}
      {activeTab === "companies" && item && (
        <CompanyLinksEditor
          companies={companies}
          linkedIds={item.company_ids || []}
          onChange={setCompanyIds}
        />
      )}
    </Modal>
  );
}

function OrdersBrowser({ orders, customers, salesRepresentatives, products, priceTables, warehouses, run }) {
  const [modal, setModal] = useState(null);
  const browser = useBrowserFilters(orders, ["order_number", "order_type", "customer_name", "price_table_name", "status"], "orders");
  const rows = browser.rows;

  function toForm(item) {
    if (!item) return emptyOrder;
    return { customer_id: `${item.customer_source}:${item.customer_external_id}`, sales_representative_id: item.sales_representative_id || "", price_table_id: item.price_table_id || "", order_type: item.order_type || "sale", order_date: item.order_date, payment_due_date: item.payment_due_date, delivery_date: item.delivery_date || "", notes: item.notes || "" };
  }

  async function save(form, item) {
    const payload = { customer_id: form.customer_id, sales_representative_id: form.sales_representative_id ? Number(form.sales_representative_id) : null, price_table_id: Number(form.price_table_id), order_type: form.order_type || "sale", order_date: form.order_date, payment_due_date: form.payment_due_date, delivery_date: form.delivery_date || null, notes: form.notes.trim() || null, items: item ? item.items.map((row) => ({ product_id: row.product_id, warehouse_id: row.warehouse_id || null, quantity: row.quantity, negotiated_unit_price: row.negotiated_unit_price })) : [] };
    const response = await run(() => item ? api.put(`/orders/${item.id}`, payload) : api.post("/orders", payload));
    if (!response) return;
    if (!response.data.payment_suggestions?.length) window.alert("Pedido salvo. Falta gerar a sugestao de pagamento.");
    setModal(null);
  }

  return (
    <Browser title="Pedidos" eyebrow="Operacoes" {...browser} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <OrderLegend />
      <BrowserDataTable browser={browser} items={rows} fallbackColumns={["Pedido", "Tipo", "Cliente", "Vendedor", "Tabela", "Pedido em", "Pagamento", "Entrega", "Total", "Lucro", "Rentab.", "Status", "Acoes"]} fallbackRows={rows.map((item) => ({
        className: orderRowClassName(item),
        cells: [
          item.order_number,
          orderTypeLabel(item.order_type),
          item.customer_name,
          item.sales_representative_name || "-",
          item.price_table_name || item.price_table_id,
          item.order_date,
          item.payment_due_date,
          item.delivery_date || "-",
          money.format(Number(item.total_amount || 0)),
          money.format(Number(item.gross_profit_amount || 0)),
          `${percent.format(Number(item.profitability_percent || 0))}%`,
          <OrderStatus status={item.status} overdue={isOrderDeliveryOverdue(item)} />,
          <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/orders/${item.id}`))} />,
        ],
      }))} rowClassName={orderRowClassName} renderActions={(item) => <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/orders/${item.id}`))} />} />
      {modal && <OrderModal state={modal} setState={setModal} customers={customers} salesRepresentatives={salesRepresentatives} products={products} priceTables={priceTables} warehouses={warehouses} run={run} onSave={save} />}
    </Browser>
  );
}

function OrderApprovalsPage({ orders, run }) {
  const [activeApproval, setActiveApproval] = useState("financial");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState({});
  const filtered = useMemo(() => {
    const pool = orders.filter((order) => ["pending_financial", "financial_blocked"].includes(order.status));
    return filterRows(pool, query, ["order_number", "customer_name", "price_table_name", "approval_notes"]);
  }, [orders, query]);
  const commercialOrders = useMemo(() => {
    const pool = orders.filter((order) => (order.authorization_reasons || []).some((reason) => reason.segment === "commercial"));
    return filterRows(pool, query, ["order_number", "customer_name", "price_table_name", "approval_notes"]);
  }, [orders, query]);

  function toggle(orderId) {
    setExpanded((current) => ({ ...current, [orderId]: !current[orderId] }));
  }

  function reasonsFor(order, segment) {
    return (order.authorization_reasons || []).filter((reason) => reason.segment === segment);
  }

  function financialActions(item) {
    return (
      <div className="row-actions">
        {activeApproval === "financial" && <button type="button" onClick={() => run(() => api.post(`/orders/${item.id}/approve-financial`))} title="Aprovar financeiro"><CheckCircle2 size={15} /></button>}
        <button type="button" onClick={() => run(() => api.post(`/orders/${item.id}/reject`))} title="Rejeitar"><XCircle size={15} /></button>
      </div>
    );
  }

  function commercialActionButtons(order, reason) {
    return (
      <div className="row-actions">
        <button type="button" onClick={() => run(() => api.post(`/orders/${order.id}/items/${reason.item_id}/approve-commercial`))} title="Autorizar item"><CheckCircle2 size={15} /></button>
        <button type="button" onClick={() => run(() => api.post(`/orders/${order.id}/reject`))} title="Rejeitar pedido"><XCircle size={15} /></button>
      </div>
    );
  }

  function approvalRows(orderList, segment) {
    return orderList.flatMap((order) => {
      const reasons = reasonsFor(order, segment);
      const base = [
        <tr key={`${segment}-${order.id}`}>
          <td><button type="button" className="link-button" onClick={() => toggle(`${segment}-${order.id}`)}>{expanded[`${segment}-${order.id}`] ? "Recolher" : "Expandir"}</button></td>
          <td>{order.order_number}</td>
          <td>{order.customer_name}</td>
          <td>{order.payment_due_date}</td>
          <td>{money.format(Number(order.total_amount || 0))}</td>
          <td>{orderStatusLabel(order.status)}</td>
          <td>{reasons.length}</td>
          <td>{segment === "financial" ? financialActions(order) : <span className="muted-inline">Autorize por motivo</span>}</td>
        </tr>,
      ];
      if (!expanded[`${segment}-${order.id}`]) return base;
      return [
        ...base,
        <tr key={`${segment}-${order.id}-reasons`}>
          <td colSpan="8">
            <AuthorizationReasons reasons={reasons} order={order} segment={segment} commercialActionButtons={commercialActionButtons} />
          </td>
        </tr>,
      ];
    });
  }

  return (
    <section className="panel">
      <div className="browser-header">
        <div>
          <p>Operacoes</p>
          <h2>Autorizacoes de pedidos</h2>
        </div>
        <div className="browser-actions">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar..." />
        </div>
      </div>
      <div className="tabs">
        <button type="button" className={activeApproval === "financial" ? "active" : ""} onClick={() => setActiveApproval("financial")}>Financeira</button>
        <button type="button" className={activeApproval === "commercial" ? "active" : ""} onClick={() => setActiveApproval("commercial")}>Comercial</button>
      </div>
      {activeApproval === "financial" && (
        <AuthorizationTable rows={approvalRows(filtered, "financial")} emptyText="Nenhum pedido aguardando autorizacao financeira." />
      )}
      {activeApproval === "commercial" && (
        <AuthorizationTable rows={approvalRows(commercialOrders, "commercial")} emptyText="Nenhum item aguardando autorizacao comercial." />
      )}
    </section>
  );
}

function AuthorizationTable({ rows, emptyText }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Motivos</th>
            <th>Pedido</th>
            <th>Cliente</th>
            <th>Prazo</th>
            <th>Total</th>
            <th>Status</th>
            <th>Qtd.</th>
            <th>Acoes</th>
          </tr>
        </thead>
        <tbody>
          {rows}
          {rows.length === 0 && <tr><td colSpan="8" className="empty">{emptyText}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function AuthorizationReasons({ reasons, order, segment, commercialActionButtons }) {
  const financial = reasons.filter((reason) => reason.segment === "financial");
  const commercial = reasons.filter((reason) => reason.segment === "commercial");
  const grouped = segment === "financial" ? [["Financeiro", financial]] : [["Comercial", commercial]];
  return (
    <div className="authorization-panel">
      {grouped.map(([title, items]) => (
        <section key={title}>
          <h3>{title}</h3>
          {items.map((reason, index) => (
            <div className="authorization-reason" key={`${reason.segment}-${reason.item_id || index}`}>
              <div>
                <strong>{reason.item_name || "Pedido"}</strong>
                <span>{reason.reason}</span>
                <small>Escopo: {reason.scope} | Status: {reason.status} | Papel sugerido: {reason.suggested_role || "-"}</small>
              </div>
              {reason.segment === "commercial" && commercialActionButtons(order, reason)}
            </div>
          ))}
          {items.length === 0 && <div className="empty-detail">Sem motivos neste segmento.</div>}
        </section>
      ))}
    </div>
  );
}

function priceCorrectionHelp(preview, priceTable) {
  if (!preview) return null;
  const mode = preview.correction_mode === "inside" ? "por dentro" : "por fora";
  const basePrice = Number(preview.base_price || 0);
  const correctedPrice = Number(preview.corrected_price || 0);
  const factor = Number(preview.correction_factor || 0);
  const monthlyRate = Number(priceTable?.monthly_rate || 0);
  const periodRate = (monthlyRate / 100) * (Number(preview.days || 0) / 30);
  const priceBeforeProgressiveDiscount = Number(preview.price_before_progressive_discount || correctedPrice);
  const progressiveDiscount = Number(preview.progressive_discount_percent || 0);
  const tierMinQuantity = Number(preview.progressive_tier_min_quantity || 0);
  const factorFormula = preview.correction_mode === "inside"
    ? `1 / (1 - ${decimal.format(periodRate)}) = ${decimal.format(factor)}`
    : `1 + ${decimal.format(periodRate)} = ${decimal.format(factor)}`;
  const progressiveLine = progressiveDiscount > 0
    ? `${money.format(priceBeforeProgressiveDiscount)} - ${percent.format(progressiveDiscount)}% pela faixa a partir de ${decimal.format(tierMinQuantity)} = ${money.format(correctedPrice)}`
    : "Sem desconto progressivo para a quantidade informada.";
  return {
    factorFormula,
    example: `${money.format(basePrice)} x fator ${decimal.format(factor)} = ${money.format(priceBeforeProgressiveDiscount)}`,
    progressiveLine,
    detail: `Taxa do periodo: ${decimal.format(monthlyRate)}% ao mes x ${preview.days} dias / 30 = ${decimal.format(periodRate)}. Como a correcao e ${mode}, o fator fica ${factorFormula}.`,
  };
}

function toPaymentRows(rows) {
  const normalizeCondition = (value) => ["avista", "parcelado", "adiantamento"].includes(value) ? value : "avista";
  return rows.map((row) => ({
    payment_method: normalizeCondition(row.payment_method),
    due_date: row.due_date || today,
    amount: String(row.amount || "0.00"),
    notes: row.notes || "",
  }));
}

function addDays(dateValue, days) {
  const date = new Date(`${dateValue || today}T00:00:00`);
  date.setDate(date.getDate() + Number(days || 0));
  return date.toISOString().slice(0, 10);
}

function OrderModal({ state, setState, customers, salesRepresentatives, products, priceTables, warehouses, run, onSave }) {
  const { item, form } = state;
  const [currentOrder, setCurrentOrder] = useState(item);
  const [itemForm, setItemForm] = useState(emptyOrderItem);
  const [editingItem, setEditingItem] = useState(null);
  const [preview, setPreview] = useState(null);
  const [paymentModalOpen, setPaymentModalOpen] = useState(false);
  const [paymentRows, setPaymentRows] = useState(() => toPaymentRows(item?.payment_suggestions || []));
  const [paymentPlan, setPaymentPlan] = useState({ condition: "avista", installments: "1", first_due_date: form.payment_due_date || today, interval_days: "30" });
  const [paymentNotice, setPaymentNotice] = useState("");
  const selectedPriceTable = priceTables.find((table) => Number(table.id) === Number(form.price_table_id));
  const correctionHelp = priceCorrectionHelp(preview, selectedPriceTable);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  const productDefaultWarehouse = (productId) => products.find((product) => String(product.id) === String(productId))?.default_warehouse_id || "";
  const paymentTotal = paymentRows.reduce((total, row) => total + Number(row.amount || 0), 0);
  const orderTotal = Number(currentOrder?.total_amount || 0);
  const paymentTotalOver = paymentTotal > orderTotal + 0.009;
  const paymentTotalMatches = Math.abs(paymentTotal - orderTotal) < 0.01;
  const availableCustomers = form.sales_representative_id
    ? customers.filter((customer) => Number(customer.sales_representative_id) === Number(form.sales_representative_id))
    : customers;

  useEffect(() => {
    setPaymentRows(toPaymentRows(currentOrder?.payment_suggestions || []));
  }, [currentOrder?.id, currentOrder?.payment_suggestions?.length]);

  useEffect(() => {
    if (!form.price_table_id || !itemForm.product_id || !form.payment_due_date) {
      setPreview(null);
      return;
    }
    api.get("/price-preview", { params: { price_table_id: form.price_table_id, product_id: itemForm.product_id, payment_due_date: form.payment_due_date, quantity: itemForm.quantity || 1 } })
      .then((response) => {
        setPreview(response.data);
        setItemForm((current) => current.negotiated_unit_price ? current : { ...current, negotiated_unit_price: String(response.data.corrected_price || "") });
      })
      .catch(() => setPreview(null));
  }, [form.price_table_id, itemForm.product_id, itemForm.quantity, form.payment_due_date]);

  async function saveHeader() {
    const payload = { customer_id: form.customer_id, sales_representative_id: form.sales_representative_id ? Number(form.sales_representative_id) : null, price_table_id: Number(form.price_table_id), order_type: form.order_type || "sale", order_date: form.order_date, payment_due_date: form.payment_due_date, delivery_date: form.delivery_date || null, notes: form.notes.trim() || null, items: currentOrder?.items?.map((row) => ({ product_id: row.product_id, warehouse_id: row.warehouse_id || null, quantity: Number(row.quantity || 0), negotiated_unit_price: Number(row.negotiated_unit_price || row.corrected_unit_price || 0) })) || [] };
    const response = currentOrder
      ? await api.put(`/orders/${currentOrder.id}`, payload)
      : await api.post("/orders", { ...payload, items: [] });
    setCurrentOrder(response.data);
    if (!response.data.payment_suggestions?.length) setPaymentNotice("Falta gerar a sugestao de pagamento do pedido.");
    else setPaymentNotice("");
    await run(async () => response);
  }

  async function reloadOrder(orderId) {
    const response = await api.get(`/orders/${orderId}`);
    setCurrentOrder(response.data);
  }

  async function submitOrder() {
    if (!currentOrder?.id) return;
    if (!currentOrder.payment_suggestions?.length) {
      setPaymentNotice("Registre a condicao de pagamento antes de enviar para aprovacao.");
      return;
    }
    const response = await api.post(`/orders/${currentOrder.id}/submit`);
    setCurrentOrder(response.data);
    await run(async () => response);
  }

  async function saveOrderItem() {
    if (!currentOrder?.id || !itemForm.product_id) return;
    const payload = { product_id: Number(itemForm.product_id), warehouse_id: itemForm.warehouse_id ? Number(itemForm.warehouse_id) : null, quantity: Number(itemForm.quantity || 0), negotiated_unit_price: itemForm.negotiated_unit_price ? Number(itemForm.negotiated_unit_price) : null };
    if (editingItem) await api.put(`/orders/${currentOrder.id}/items/${editingItem.id}`, payload);
    else await api.post(`/orders/${currentOrder.id}/items`, payload);
    setEditingItem(null);
    setItemForm(emptyOrderItem);
    await reloadOrder(currentOrder.id);
    await run(async () => ({ data: true }));
  }

  async function removeOrderItem(row) {
    await api.delete(`/orders/${currentOrder.id}/items/${row.id}`);
    await reloadOrder(currentOrder.id);
    await run(async () => ({ data: true }));
  }

  async function cancelOrderItem(row) {
    const remaining = Number(row.quantity || 0) - Number(row.cancelled_quantity || 0);
    const value = window.prompt(`Quantidade para cancelar. Saldo atual: ${decimal.format(remaining)}`, String(remaining));
    if (!value) return;
    await api.post(`/orders/${currentOrder.id}/items/${row.id}/cancel`, { quantity: Number(value.replace(",", ".")) });
    await reloadOrder(currentOrder.id);
    await run(async () => ({ data: true }));
  }

  async function cancelOrder() {
    if (!currentOrder?.id || !window.confirm("Cancelar o pedido inteiro?")) return;
    const response = await api.post(`/orders/${currentOrder.id}/cancel`);
    setCurrentOrder(response.data);
    await run(async () => response);
  }

  async function generatePayments() {
    if (!currentOrder?.id) return;
    const total = Number(currentOrder.total_amount || 0);
    const installments = paymentPlan.condition === "parcelado" ? Math.max(1, Number(paymentPlan.installments || 1)) : 1;
    const baseAmount = Math.floor((total / installments) * 100) / 100;
    const rows = Array.from({ length: installments }, (_, index) => {
      const amount = index === installments - 1 ? (total - baseAmount * (installments - 1)) : baseAmount;
      const dueDate = paymentPlan.condition === "adiantamento"
        ? (paymentPlan.first_due_date || form.order_date || today)
        : addDays(paymentPlan.first_due_date || form.payment_due_date || today, index * Number(paymentPlan.interval_days || 30));
      return {
        payment_method: paymentPlan.condition,
        due_date: dueDate,
        amount: amount.toFixed(2),
        notes: paymentPlan.condition === "parcelado" ? `Parcela ${index + 1}/${installments}` : "",
      };
    });
    setPaymentRows(rows);
    setPaymentNotice("");
  }

  async function savePayments() {
    if (!currentOrder?.id) return;
    if (!paymentRows.length) {
      setPaymentNotice("Informe ao menos uma parcela ou gere uma sugestao.");
      return;
    }
    if (paymentTotalOver) {
      setPaymentNotice("O total sugerido nao pode passar o valor do pedido.");
      return;
    }
    if (!paymentTotalMatches) {
      setPaymentNotice("O total sugerido precisa fechar com o total do pedido.");
      return;
    }
    const payload = paymentRows.map((row) => ({
      payment_method: row.payment_method,
      due_date: row.due_date,
      amount: Number(row.amount || 0),
      notes: row.notes.trim() || null,
    }));
    try {
      const response = await api.put(`/orders/${currentOrder.id}/payment-suggestions`, payload);
      setCurrentOrder(response.data);
      setPaymentRows(toPaymentRows(response.data.payment_suggestions || []));
      setPaymentNotice("");
      await run(async () => response);
    } catch (error) {
      setPaymentNotice(error?.response?.data?.detail || "Nao foi possivel salvar a sugestao de pagamento.");
    }
  }

  function updatePaymentRow(index, field, value) {
    setPaymentRows((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
    setPaymentNotice("");
  }

  function addPaymentRow() {
    if (paymentTotal >= orderTotal - 0.009) {
      setPaymentNotice("O total sugerido ja atingiu o valor do pedido. Reduza uma parcela antes de adicionar outra.");
      return;
    }
    setPaymentRows((current) => [...current, { ...emptyPaymentSuggestion, due_date: form.payment_due_date, amount: "0.00" }]);
    setPaymentNotice("");
  }

  function removePaymentRow(index) {
    setPaymentRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  function editOrderItem(row) {
    setEditingItem(row);
    setItemForm({ product_id: row.product_id || "", warehouse_id: row.warehouse_id || productDefaultWarehouse(row.product_id), quantity: String(row.quantity || "1"), negotiated_unit_price: String(row.negotiated_unit_price || row.corrected_unit_price || "") });
  }

  return (
    <Modal title={currentOrder ? `Editar pedido ${currentOrder.order_number}` : "Novo pedido"} onClose={() => setState(null)} onSubmit={() => onSave(form, currentOrder)}>
      <div className="modal-grid">
        <Field label="Vendedor"><Select value={form.sales_representative_id || ""} onChange={(value) => setState({ ...state, form: { ...form, sales_representative_id: value, customer_id: "" } })} options={salesRepresentatives.filter((representative) => representative.active)} empty="Automatico pela carteira" labelKey="user_name" /></Field>
        <Field label="Cliente" wide><Select value={form.customer_id} onChange={(v) => update("customer_id", v)} options={availableCustomers} empty="Selecione" required labelKey="name" valueKey="id" /></Field>
        <Field label="Tipo"><select value={form.order_type || "sale"} onChange={(event) => update("order_type", event.target.value)}><option value="sale">Pedido de venda</option><option value="purchase">Pedido de compra</option></select></Field>
        <Field label="Tabela"><Select value={form.price_table_id} onChange={(v) => update("price_table_id", v)} options={priceTables} empty="Selecione" required /></Field>
        <Field label="Prazo pagamento"><input type="date" value={form.payment_due_date} onChange={(e) => update("payment_due_date", e.target.value)} /></Field>
        <Field label="Previsao entrega"><input type="date" value={form.delivery_date} onChange={(e) => update("delivery_date", e.target.value)} /></Field>
        <Field label="Data pedido"><input type="date" value={form.order_date} onChange={(e) => update("order_date", e.target.value)} /></Field>
        <Field label="Observacao" wide><input value={form.notes} onChange={(e) => update("notes", e.target.value)} /></Field>
        {currentOrder?.approval_notes && <Field label="Autorizacao" wide><input disabled value={currentOrder.approval_notes} /></Field>}
        <div className="form-actions"><button type="button" className="secondary-button" onClick={saveHeader}>{currentOrder ? "Salvar cabecalho" : "Salvar cabecalho para itens"}</button></div>
        {currentOrder?.id && <div className="form-actions"><button type="button" className="secondary-button" onClick={() => setPaymentModalOpen(true)}><CreditCard size={16} /> Pagamento</button></div>}
        {currentOrder?.status === "draft" && <div className="form-actions"><button type="button" className="primary-button" onClick={submitOrder}><Send size={16} /> Enviar para aprovacao</button></div>}
        {currentOrder?.id && !["cancelled", "rejected"].includes(currentOrder.status) && <div className="form-actions"><button type="button" className="secondary-button" onClick={cancelOrder}>Cancelar pedido</button></div>}
      </div>

      {paymentNotice && <div className="inline-alert">{paymentNotice}</div>}

      <section className="modal-detail">
        {currentOrder?.id && (
          <div className="order-context">
            <span>Tipo <strong>{orderTypeLabel(currentOrder.order_type)}</strong></span>
            <span>Status <OrderStatus status={currentOrder.status} overdue={isOrderDeliveryOverdue(currentOrder)} /></span>
            <span>Pagamento <strong>{currentOrder.payment_due_date}</strong></span>
            <span>Cond. pgto. <strong>{currentOrder.payment_suggestions?.length ? `${currentOrder.payment_suggestions.length} sugestao(oes)` : "Pendente"}</strong></span>
            <span>Entrega <strong>{currentOrder.delivery_date || "Nao informada"}</strong></span>
            <span>Cliente <strong>{currentOrder.customer_name}</strong></span>
            <span>Vendedor <strong>{currentOrder.sales_representative_name || "Nao informado"}</strong></span>
          </div>
        )}
        <div className="panel-header">
          <div>
            <p>Itens do pedido</p>
            <h2>Produtos</h2>
          </div>
        </div>

        {!currentOrder?.id && <div className="empty-detail">Salve o cabecalho do pedido para incluir produtos.</div>}

        {currentOrder?.id && (
          <>
            <div className="detail-form">
              <Field label="Produto" wide><Select value={itemForm.product_id} onChange={(v) => setItemForm({ ...itemForm, product_id: v, warehouse_id: productDefaultWarehouse(v), negotiated_unit_price: "" })} options={products} empty="Selecione" /></Field>
              <Field label="Local"><Select value={itemForm.warehouse_id} onChange={(v) => setItemForm({ ...itemForm, warehouse_id: v })} options={warehouses} empty="Sem local" /></Field>
              <Field label="Quantidade"><input type="number" min="0.0001" step="0.0001" value={itemForm.quantity} onChange={(e) => setItemForm({ ...itemForm, quantity: e.target.value, negotiated_unit_price: "" })} /></Field>
              <Field label="Valor negociado"><input type="number" min="0" step="0.01" value={itemForm.negotiated_unit_price} onChange={(e) => setItemForm({ ...itemForm, negotiated_unit_price: e.target.value })} /></Field>
              <div className="form-actions">
                {editingItem && <button type="button" className="secondary-button" onClick={() => { setEditingItem(null); setItemForm(emptyOrderItem); }}>Cancelar item</button>}
                <button type="button" className="primary-button" onClick={saveOrderItem}>{editingItem ? "Salvar item" : "Incluir item"}</button>
              </div>
            </div>
            <DataTable columns={["Produto", "Local", "Qtd.", "Cancel.", "Preco tabela", "Negociado", "Comercial", "Total", "Lucro", "Acoes"]} rows={(currentOrder.items || []).map((row) => [
              `${row.product_sku} - ${row.product_name}`,
              row.warehouse_name || "-",
              decimal.format(Number(row.quantity || 0)),
              decimal.format(Number(row.cancelled_quantity || 0)),
              money.format(Number(row.corrected_unit_price || 0)),
              money.format(Number(row.negotiated_unit_price || 0)),
              <CommercialStatus status={row.commercial_status} />,
              money.format(Number(row.total_amount || 0)),
              money.format(Number(row.gross_profit_amount || 0)),
              <div className="row-actions">
                <button type="button" onClick={() => editOrderItem(row)} title="Editar"><Edit3 size={15} /></button>
                <button type="button" onClick={() => cancelOrderItem(row)} title="Cancelar quantidade">Canc.</button>
                <button type="button" onClick={() => window.confirm("Confirma a exclusao?") && removeOrderItem(row)} title="Excluir"><Trash2 size={15} /></button>
              </div>,
            ])} />
            <div className="order-summary">
              <span>Total: <strong>{money.format(Number(currentOrder.total_amount || 0))}</strong></span>
              <span>Custo: <strong>{money.format(Number(currentOrder.total_cost_amount || 0))}</strong></span>
              <span>Lucro: <strong>{money.format(Number(currentOrder.gross_profit_amount || 0))}</strong></span>
              <span>Rentabilidade do pedido: <strong>{percent.format(Number(currentOrder.profitability_percent || 0))}%</strong></span>
            </div>
          </>
        )}

        <div className="price-preview">
          <strong>{preview ? money.format(Number(preview.corrected_price || 0)) : "-"}</strong>
          <div className="price-preview-meta">
            <span>{preview ? `${preview.days} dias, ${preview.correction_mode === "inside" ? "por dentro" : "por fora"}${Number(preview.progressive_discount_percent || 0) > 0 ? `, desc. ${percent.format(Number(preview.progressive_discount_percent))}%` : ""}` : "Preco corrigido"}</span>
            {correctionHelp && (
              <button type="button" className="help-tip" aria-label="Entenda o calculo do preco corrigido">
                <HelpCircle size={15} />
                <span className="help-bubble">
                  <strong>Entenda o calculo</strong>
                  <span>Fator: {correctionHelp.factorFormula}</span>
                  <span>{correctionHelp.example}</span>
                  <span>{correctionHelp.progressiveLine}</span>
                  <small>{correctionHelp.detail}</small>
                </span>
              </button>
            )}
          </div>
        </div>
      </section>
      {paymentModalOpen && (
        <div className="nested-modal-backdrop">
          <div className="nested-modal">
            <header>
              <h3>Sugestao de pagamento</h3>
              <button type="button" className="icon-button" onClick={() => setPaymentModalOpen(false)}><X size={18} /></button>
            </header>
            <div className="payment-actions">
              <Field label="Condicao">
                <select value={paymentPlan.condition} onChange={(event) => setPaymentPlan({ ...paymentPlan, condition: event.target.value, installments: event.target.value === "parcelado" ? paymentPlan.installments : "1" })}>
                  <option value="avista">A vista</option>
                  <option value="parcelado">Parcelado</option>
                  <option value="adiantamento">Adiantamento</option>
                </select>
              </Field>
              <Field label="Parcelas">
                <input type="number" min="1" step="1" disabled={paymentPlan.condition !== "parcelado"} value={paymentPlan.installments} onChange={(event) => setPaymentPlan({ ...paymentPlan, installments: event.target.value })} />
              </Field>
              <Field label="Primeiro venc.">
                <input type="date" value={paymentPlan.first_due_date} onChange={(event) => setPaymentPlan({ ...paymentPlan, first_due_date: event.target.value })} />
              </Field>
              <Field label="Intervalo dias">
                <input type="number" min="1" step="1" disabled={paymentPlan.condition !== "parcelado"} value={paymentPlan.interval_days} onChange={(event) => setPaymentPlan({ ...paymentPlan, interval_days: event.target.value })} />
              </Field>
              <button type="button" className="secondary-button" onClick={generatePayments}>Gerar sugestao</button>
              <button type="button" className="secondary-button" onClick={addPaymentRow} disabled={paymentTotal >= orderTotal - 0.009}>Adicionar parcela</button>
            </div>
            {paymentNotice && <div className={`inline-alert ${paymentTotalOver ? "danger" : ""}`}>{paymentNotice}</div>}
            <DataTable columns={["Condicao", "Vencimento", "Valor", "Observacao", "Acoes"]} rows={paymentRows.map((row, index) => [
              <select value={row.payment_method} onChange={(event) => updatePaymentRow(index, "payment_method", event.target.value)}>
                <option value="avista">A vista</option>
                <option value="parcelado">Parcelado</option>
                <option value="adiantamento">Adiantamento</option>
              </select>,
              <input type="date" value={row.due_date} onChange={(event) => updatePaymentRow(index, "due_date", event.target.value)} />,
              <input type="number" min="0.01" step="0.01" value={row.amount} onChange={(event) => updatePaymentRow(index, "amount", event.target.value)} />,
              <input value={row.notes} onChange={(event) => updatePaymentRow(index, "notes", event.target.value)} />,
              <button type="button" className="secondary-button compact-button" onClick={() => removePaymentRow(index)}>Remover</button>,
            ])} />
            <div className={`payment-total ${paymentTotalOver ? "over" : ""}`}>
              <span>Total sugerido: <strong>{money.format(paymentTotal)}</strong></span>
              <span>Total pedido: <strong>{money.format(orderTotal)}</strong></span>
            </div>
            <footer>
              <button type="button" className="secondary-button" onClick={() => setPaymentModalOpen(false)}>Fechar</button>
              <button type="button" className="primary-button" onClick={savePayments}>Salvar sugestao</button>
            </footer>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Browser({ title, eyebrow, filters = [], setFilters, filterFields = [], browserOptions = [], selectedBrowserId, setSelectedBrowserId, onNew, children }) {
  const selectedBrowser = browserOptions.find((item) => String(item.id) === String(selectedBrowserId));
  return (
    <section className="panel">
      <div className="browser-header">
        <div>
          <p>{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        <div className="browser-actions">
          {onNew && <button className="primary-button" onClick={onNew}><Plus size={17} /> Novo</button>}
        </div>
      </div>
      {browserOptions.length > 0 && (
        <div className="browser-query-row">
          <label>
            <span>Consulta</span>
            <select value={selectedBrowserId || ""} onChange={(event) => setSelectedBrowserId?.(event.target.value)}>
              {browserOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          {selectedBrowser && <span className={`query-kind ${selectedBrowser.is_standard ? "standard" : "custom"}`}>{selectedBrowser.is_standard ? "Padrao" : "Personalizada"}</span>}
        </div>
      )}
      {setFilters && <BrowserFilters filters={filters} setFilters={setFilters} fields={filterFields} />}
      {children}
    </section>
  );
}

function BrowserFilters({ filters, setFilters, fields }) {
  const activeFilters = filters.length ? filters : [];
  const appliedFilters = activeFilters.filter(hasActiveFilter);
  const [draft, setDraft] = useState(() => emptyBrowserFilter());
  const [editingId, setEditingId] = useState(null);
  const draftField = fieldByName(fields, draft.field);
  const draftOperators = operatorsForField(draftField);
  const draftOperator = draftOperators.some((item) => item.value === draft.operator) ? draft.operator : draftOperators[0].value;

  useEffect(() => {
    setDraft(emptyBrowserFilter());
    setEditingId(null);
  }, [fields]);

  function updateDraft(patch) {
    setDraft((current) => {
      const next = normalizeBrowserFilter({ ...current, ...patch }, fields);
      if (fieldByName(fields, next.field).type === "boolean" && !String(next.value || "").trim()) {
        next.value = "true";
      }
      return next;
    });
  }

  function addFilter() {
    const nextFilter = normalizeBrowserFilter({ ...draft, operator: draftOperator, id: editingId || draft.id }, fields);
    if (!hasActiveFilter(nextFilter)) return;
    const existing = activeFilters.filter(hasActiveFilter);
    const next = editingId
      ? existing.map((filter) => filter.id === editingId && !filter.fixed ? nextFilter : filter)
      : [...existing, nextFilter];
    setFilters(next.length ? next : [emptyBrowserFilter()]);
    setDraft(emptyBrowserFilter());
    setEditingId(null);
  }

  function removeFilter(id) {
    const next = activeFilters.filter((filter) => filter.id !== id || filter.required || filter.fixed).filter(hasActiveFilter);
    setFilters(next.length ? next : [emptyBrowserFilter()]);
  }

  function clearFilters() {
    const kept = activeFilters.filter((filter) => (filter.required || filter.fixed) && hasActiveFilter(filter));
    setFilters(kept.length ? kept : [emptyBrowserFilter()]);
    setDraft(emptyBrowserFilter());
    setEditingId(null);
  }

  return (
    <div className="browser-filters">
      <div className="browser-filter-title"><Filter size={16} /><span>Filtros</span></div>
      <div className="browser-filter-row">
        <select value={draft.field} onChange={(event) => updateDraft({ field: event.target.value, operator: "" })}>
          <option value="__all__">Busca geral</option>
          {fields.map((field) => <option key={field.name} value={field.name}>{field.label}</option>)}
        </select>
        <select value={draftOperator} onChange={(event) => updateDraft({ operator: event.target.value })}>
          {draftOperators.map((operator) => <option key={operator.value} value={operator.value}>{operator.label}</option>)}
        </select>
        <FilterValueInput filter={draft} field={draftField} operator={draftOperator} onChange={updateDraft} />
      </div>
      <div className="browser-filter-actions">
        <div className="filter-chip-list">
          {appliedFilters.map((filter) => (
            <span key={filter.id} className={`filter-chip ${filter.fixed ? "locked" : ""}`} onDoubleClick={() => { if (!filter.fixed) { setDraft({ ...filter }); setEditingId(filter.id); } }}>
              {filterTagLabel(filter, fields)}
              {!filter.fixed && !filter.required && <button type="button" onClick={() => removeFilter(filter.id)} title="Remover filtro"><X size={13} /></button>}
            </span>
          ))}
        </div>
        <div className="browser-filter-buttons">
          {editingId && <button type="button" className="secondary-button" onClick={() => { setDraft(emptyBrowserFilter()); setEditingId(null); }}>Cancelar</button>}
          <button type="button" className="secondary-button" disabled={!hasActiveFilter({ ...draft, operator: draftOperator })} onClick={addFilter}><Plus size={16} /> {editingId ? "Atualizar" : "Filtro"}</button>
          <button type="button" className="secondary-button" onClick={clearFilters}>Limpar</button>
        </div>
      </div>
    </div>
  );
}

function FilterValueInput({ filter, field, operator, onChange }) {
  if (operator === "is_empty" || operator === "is_not_empty") return <div className="filter-empty-value">Sem valor</div>;
  if (operator === "between") {
    return (
      <div className="filter-between">
        <input type={inputTypeForField(field)} value={filter.value || ""} onChange={(event) => onChange({ value: event.target.value })} placeholder="Inicial" />
        <input type={inputTypeForField(field)} value={filter.valueTo || ""} onChange={(event) => onChange({ valueTo: event.target.value })} placeholder="Final" />
      </div>
    );
  }
  if (field?.type === "boolean") {
    return <select value={filter.value || "true"} onChange={(event) => onChange({ value: event.target.value })}><option value="true">Sim</option><option value="false">Nao</option></select>;
  }
  return <input type={inputTypeForField(field)} value={filter.value || ""} onChange={(event) => onChange({ value: event.target.value })} placeholder="Valor" />;
}

function Modal({ title, onClose, onSubmit, children }) {
  return (
    <div className="modal-backdrop">
      <form className="modal" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <header>
          <h2>{title}</h2>
          <button type="button" className="icon-button" onClick={onClose}><X size={18} /></button>
        </header>
        {children}
        <footer>
          <button type="button" className="secondary-button" onClick={onClose}>Cancelar</button>
          <button className="primary-button">Salvar</button>
        </footer>
      </form>
    </div>
  );
}

function Field({ label, wide, children }) {
  return <label className={wide ? "span-2" : ""}><span>{label}</span>{children}</label>;
}

function Check({ label, checked, onChange }) {
  return <label className="check-row"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /> {label}</label>;
}

function CompanyLinksEditor({ companies, linkedIds, onChange }) {
  const [selected, setSelected] = useState(() => new Set((linkedIds || []).map(String)));
  useEffect(() => {
    const initial = (linkedIds || []).map(String);
    setSelected(new Set(initial));
    onChange?.(initial.map(Number));
  }, [linkedIds]);
  function toggle(companyId, checked) {
    const next = new Set(selected);
    if (checked) next.add(String(companyId));
    else next.delete(String(companyId));
    setSelected(next);
    onChange?.(Array.from(next).map(Number));
  }
  return (
    <div className="company-links">
      {companies.map((company) => (
        <label className="company-link-row" key={company.id}>
          <input type="checkbox" checked={selected.has(String(company.id))} onChange={(event) => toggle(company.id, event.target.checked)} />
          <span>
            <strong>{company.code} - {company.name}</strong>
            <small>{company.company_kind === "branch" ? "Filial" : "Matriz"}</small>
          </span>
        </label>
      ))}
      {companies.length === 0 && <div className="empty-detail">Nenhuma empresa cadastrada.</div>}
    </div>
  );
}

function Select({ value, onChange, options, empty, required, labelKey = "name", valueKey = "id" }) {
  return (
    <select required={required} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">{empty}</option>
      {options.map((item) => <option key={item[valueKey]} value={item[valueKey]}>{item.code ? `${item.code} - ${item[labelKey]}` : item[labelKey]}</option>)}
    </select>
  );
}

function RowActions({ onEdit, onRemove, extraLabel, onExtra }) {
  return (
    <div className="row-actions">
      {onExtra && <button type="button" onClick={onExtra}>{extraLabel}</button>}
      <button type="button" onClick={onEdit} title="Editar"><Edit3 size={15} /></button>
      <button type="button" onClick={() => window.confirm("Confirma a exclusao?") && onRemove()} title="Excluir"><Trash2 size={15} /></button>
    </div>
  );
}

function Status({ active }) {
  return <span className={`status-pill ${active ? "active" : "inactive"}`}>{active ? "Ativo" : "Inativo"}</span>;
}

function isOrderDeliveryOverdue(order) {
  return Boolean(order.delivery_date && order.delivery_date < today && !["cancelled", "rejected"].includes(order.status));
}

function isOrderInApproval(order) {
  return ["pending_financial", "financial_blocked", "pending_commercial"].includes(order.status);
}

function orderRowClassName(order) {
  return [
    isOrderInApproval(order) ? "order-row-approval" : "",
    isOrderDeliveryOverdue(order) ? "order-row-overdue" : "",
  ].filter(Boolean).join(" ");
}

function OrderLegend() {
  return (
    <div className="order-legend">
      <span><i className="legend-dot approval" /> Em autorizacao</span>
      <span><i className="legend-dot overdue" /> Entrega vencida</span>
      <span><i className="legend-dot approved" /> Autorizado</span>
    </div>
  );
}

function OrderStatus({ status, overdue }) {
  return <span className={`status-pill order-status ${status} ${overdue ? "overdue" : ""}`}>{overdue ? "Entrega vencida" : orderStatusLabel(status)}</span>;
}

function orderStatusLabel(status) {
  const labels = {
    draft: "Rascunho",
    pending_financial: "Aprov. financeira",
    financial_blocked: "Bloqueado financeiro",
    pending_commercial: "Autoriz. comercial",
    approved: "Autorizado",
    rejected: "Rejeitado",
    cancelled: "Cancelado",
  };
  return labels[status] || status;
}

function orderTypeLabel(type) {
  const labels = {
    purchase: "Pedido de compra",
    sale: "Pedido de venda",
  };
  return labels[type] || "Pedido de venda";
}

function CommercialStatus({ status }) {
  return <span className={`status-pill commercial-status ${status || "empty"}`}>{commercialStatusLabel(status)}</span>;
}

function commercialStatusLabel(status) {
  const labels = {
    approved: "Aprovado",
    pending: "Pendente",
    rejected: "Rejeitado",
  };
  return labels[status] || status || "-";
}

function healthStatusLabel(status) {
  const labels = {
    critical: "Critico",
    attention: "Atencao",
    healthy: "Saudavel",
  };
  return labels[status] || status;
}

function DataTable({ columns, rows, className = "" }) {
  const [sort, setSort] = useState({ index: null, direction: null });
  const sortedRows = useMemo(() => sortTableRows(rows, sort), [rows, sort]);
  return (
    <div className="table-wrap">
      <table className={className}>
        <thead><tr>{columns.map((column, index) => {
          const definition = tableColumnDefinition(column);
          const active = sort.index === index ? sort.direction : null;
          return <th key={`${definition.label}-${index}`} className={definition.sortable ? `sortable-column ${active || ""}` : ""}><button type="button" disabled={!definition.sortable} onClick={() => setSort(nextTableSort(sort, index))}>{definition.label}{definition.sortable && <span className="sort-indicator">{active === "asc" ? "↑" : active === "desc" ? "↓" : "↕"}</span>}</button></th>;
        })}</tr></thead>
        <tbody>
          {sortedRows.map((row, index) => {
            const cells = Array.isArray(row) ? row : row.cells;
            return <tr key={index} className={Array.isArray(row) ? "" : row.className}>{cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>;
          })}
          {rows.length === 0 && <tr><td colSpan={columns.length} className="empty">Nenhum registro encontrado.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function BrowserDataTable({ browser, items, fallbackColumns, fallbackRows, renderActions, rowClassName }) {
  const fields = browser.selectedBrowser?.columns || [];
  if (!fields.length) return <DataTable columns={fallbackColumns} rows={fallbackRows} />;
  return (
    <DataTable
      className={browser.selectedBrowser?.entity_code === "orders" ? "orders-table" : ""}
      columns={[...fields.map((field) => ({ label: field.label || browserFieldLabel(field.name), sortable: field.sortable !== false })), ...(renderActions ? [{ label: "Acoes", sortable: false }] : [])]}
      rows={items.map((item) => ({
        className: rowClassName?.(item) || "",
        cells: [
          ...fields.map((field) => browserCellValue(item, field)),
          ...(renderActions ? [renderActions(item)] : []),
        ],
      }))}
    />
  );
}

function tableColumnDefinition(column) {
  if (typeof column === "object") return { label: column.label, sortable: column.sortable !== false };
  return { label: column, sortable: String(column).toLowerCase() !== "acoes" };
}

function nextTableSort(current, index) {
  if (current.index !== index) return { index, direction: "asc" };
  if (current.direction === "asc") return { index, direction: "desc" };
  if (current.direction === "desc") return { index: null, direction: null };
  return { index, direction: "asc" };
}

function sortTableRows(rows, sort) {
  if (sort.index === null || !sort.direction) return rows;
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const leftCells = Array.isArray(left.row) ? left.row : left.row.cells;
    const rightCells = Array.isArray(right.row) ? right.row : right.row.cells;
    const compared = compareTableValues(tableCellSortValue(leftCells[sort.index]), tableCellSortValue(rightCells[sort.index]));
    return compared ? compared * (sort.direction === "asc" ? 1 : -1) : left.index - right.index;
  }).map((item) => item.row);
}

function tableCellSortValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.map(tableCellSortValue).join(" ");
  if (value?.props?.active !== undefined) return value.props.active ? "ativo" : "inativo";
  if (value?.props?.status !== undefined) return value.props.status;
  if (value?.props?.children !== undefined) return tableCellSortValue(value.props.children);
  return String(value);
}

function compareTableValues(left, right) {
  const leftText = String(left ?? "").trim();
  const rightText = String(right ?? "").trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(leftText) && /^\d{4}-\d{2}-\d{2}/.test(rightText)) return leftText.localeCompare(rightText);
  const parseNumber = (value) => Number(value.replace(/[^\d,.-]/g, "").replace(/\.(?=\d{3}(?:\D|$))/g, "").replace(",", "."));
  const leftNumber = parseNumber(leftText);
  const rightNumber = parseNumber(rightText);
  if (leftText && rightText && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return leftText.localeCompare(rightText, "pt-BR", { numeric: true, sensitivity: "base" });
}

function browserCellValue(item, field) {
  const value = item?.[field.name];
  if (field.name === "active") return <Status active={Boolean(value)} />;
  if (field.name === "status") return <OrderStatus status={value} overdue={isOrderDeliveryOverdue(item)} />;
  if (field.name === "order_type") return orderTypeLabel(value);
  if (field.name === "correction_mode") return value === "inside" ? "Por dentro" : "Por fora";
  if (value === null || value === undefined || value === "") return "-";
  if (field.type === "boolean") return value ? "Sim" : "Nao";
  if (field.type === "date") return String(value).slice(0, 10);
  if (field.type === "number") {
    if (field.name.includes("amount") || field.name.includes("price") || field.name.includes("cost")) return money.format(Number(value || 0));
    if (field.name.includes("percent") || field.name.includes("margin") || field.name.includes("rate")) return `${percent.format(Number(value || 0))}%`;
    return decimal.format(Number(value || 0));
  }
  return String(value);
}

function useBrowserFilters(items, priorityFields = [], entityCode = null) {
  const definitions = useContext(BrowserDefinitionsContext);
  const globalSearch = useContext(GlobalSearchContext);
  const [filters, setFilters] = useState(() => [emptyBrowserFilter()]);
  const [selectedBrowserId, setSelectedBrowserId] = useState("");
  const priorityKey = priorityFields.join("|");
  const browserOptions = useMemo(
    () => entityCode ? definitions.filter((browser) => browser.entity_code === entityCode) : [],
    [definitions, entityCode],
  );
  useEffect(() => {
    if (browserOptions.length && !browserOptions.some((browser) => String(browser.id) === String(selectedBrowserId))) {
      const standard = browserOptions.find((browser) => browser.is_standard) || browserOptions[0];
      setSelectedBrowserId(String(standard.id));
    }
  }, [browserOptions, selectedBrowserId]);
  const selectedBrowser = useMemo(
    () => browserOptions.find((browser) => String(browser.id) === String(selectedBrowserId)) || browserOptions[0] || null,
    [browserOptions, selectedBrowserId],
  );
  useEffect(() => {
    setFilters(defaultFiltersForBrowser(selectedBrowser).visible);
  }, [selectedBrowser?.id]);
  const filterFields = useMemo(
    () => buildBrowserFilterFields(items, priorityFields, selectedBrowser),
    [items, priorityKey, selectedBrowser],
  );
  const hiddenFilters = useMemo(() => defaultFiltersForBrowser(selectedBrowser).hidden, [selectedBrowser?.id]);
  const rows = useMemo(() => {
    const filtered = filterRows(items, [...filters, ...hiddenFilters], filterFields);
    const term = globalSearch.trim().toLowerCase();
    if (!term) return filtered;
    return filtered.filter((item) => filterFields.some((field) => String(item?.[field.name] ?? "").toLowerCase().includes(term)));
  }, [items, filters, hiddenFilters, filterFields, globalSearch]);
  return { rows, filters, setFilters, filterFields, browserOptions, selectedBrowserId: selectedBrowser?.id || "", setSelectedBrowserId, selectedBrowser };
}

function defaultFiltersForBrowser(browser) {
  const configured = (browser?.filters || []).filter((filter) => filter.behavior !== "disabled");
  const visible = configured.filter((filter) => filter.behavior !== "fixed_hidden").map(browserFilterFromDefinition);
  const hidden = configured.filter((filter) => filter.behavior === "fixed_hidden").map(browserFilterFromDefinition);
  return { visible: visible.length ? visible : [emptyBrowserFilter()], hidden };
}

function browserFilterFromDefinition(filter) {
  return {
    id: browserFilterId(),
    field: filter.field || "__all__",
    operator: filter.operator || "equals",
    value: resolveFilterToken(filter.value, filter.valueKind),
    valueTo: resolveFilterToken(filter.valueTo, filter.valueKind),
    fixed: filter.behavior === "fixed_visible",
    required: Boolean(filter.required),
  };
}

function resolveFilterToken(value, valueKind) {
  if (!value) return "";
  const raw = String(value);
  if (valueKind === "fixed" && !raw.startsWith(":")) return raw;
  const current = new Date();
  const year = current.getFullYear();
  const month = current.getMonth();
  const dateText = (date) => date.toISOString().slice(0, 10);
  return ({
    ":TODAY": dateText(current),
    ":START_OF_YEAR": `${year}-01-01`,
    ":END_OF_YEAR": `${year}-12-31`,
    ":START_OF_MONTH": dateText(new Date(year, month, 1)),
    ":END_OF_MONTH": dateText(new Date(year, month + 1, 0)),
    ":ACTIVE_COMPANY_ID": localStorage.getItem("easy-active-company-id") || "",
  })[raw] ?? raw;
}

function emptyBrowserFilter() {
  return { id: browserFilterId(), field: "__all__", operator: "contains", value: "", valueTo: "" };
}

function browserFilterId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `filter-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function buildBrowserFilterFields(items, priorityFields, selectedBrowser) {
  if (selectedBrowser?.columns?.length) {
    return selectedBrowser.columns.filter((field) => field.filterable !== false).map((field) => ({
      name: field.name,
      label: field.label || browserFieldLabel(field.name),
      type: field.type || inferBrowserFieldType(items, field.name),
    }));
  }
  const names = new Set(priorityFields);
  items.forEach((item) => Object.entries(item || {}).forEach(([key, value]) => {
    if (!Array.isArray(value) && typeof value !== "object") names.add(key);
  }));
  return Array.from(names).map((name) => ({ name, label: browserFieldLabel(name), type: inferBrowserFieldType(items, name) }));
}

function browserFieldLabel(name) {
  const labels = {
    active: "Status", base_date: "Data-base", code: "Codigo", customer_count: "Clientes",
    customer_name: "Cliente", customer_profile_name: "Perfil", delivery_date: "Entrega",
    document_number: "CPF/CNPJ", gross_profit_amount: "Lucro", monthly_rate: "Taxa mensal",
    name: "Nome", order_date: "Pedido em", order_number: "Pedido", order_type: "Tipo",
    payment_due_date: "Pagamento", price_table_name: "Tabela", profitability_percent: "Rentabilidade",
    sale_price: "Preco sugerido", sales_representative_name: "Vendedor", sku: "SKU",
    status: "Status", total_amount: "Total", user_name: "Vendedor", whatsapp_number: "WhatsApp",
  };
  return labels[name] || name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function inferBrowserFieldType(items, fieldName) {
  const sample = items.map((item) => item?.[fieldName]).find((value) => value !== null && value !== undefined && value !== "");
  if (typeof sample === "boolean") return "boolean";
  if (typeof sample === "number") return "number";
  if (typeof sample === "string" && /^\d{4}-\d{2}-\d{2}/.test(sample)) return "date";
  if (sample !== undefined && sample !== null && sample !== "" && !Number.isNaN(Number(sample)) && !String(sample).startsWith("0")) return "number";
  return "text";
}

function fieldByName(fields, name) {
  if (name === "__all__") return { name, label: "Busca geral", type: "text" };
  return fields.find((field) => field.name === name) || { name, label: browserFieldLabel(name), type: "text" };
}

function operatorsForField(field) {
  if (field?.type === "number" || field?.type === "date") return [
    { value: "equals", label: "Igual" }, { value: "greater_than", label: "Maior" },
    { value: "greater_or_equal", label: "Maior/igual" }, { value: "less_than", label: "Menor" },
    { value: "less_or_equal", label: "Menor/igual" }, { value: "between", label: "Entre" },
    { value: "is_empty", label: "Vazio" }, { value: "is_not_empty", label: "Preenchido" },
  ];
  if (field?.type === "boolean") return [
    { value: "equals", label: "Igual" }, { value: "is_empty", label: "Vazio" }, { value: "is_not_empty", label: "Preenchido" },
  ];
  return [
    { value: "contains", label: "Contem" }, { value: "equals", label: "Igual" },
    { value: "starts_with", label: "Comeca" }, { value: "ends_with", label: "Termina" },
    { value: "not_contains", label: "Nao contem" }, { value: "is_empty", label: "Vazio" },
    { value: "is_not_empty", label: "Preenchido" },
  ];
}

function normalizeBrowserFilter(filter, fields) {
  const operators = operatorsForField(fieldByName(fields, filter.field));
  return { ...filter, operator: operators.some((item) => item.value === filter.operator) ? filter.operator : operators[0].value };
}

function inputTypeForField(field) {
  if (field?.type === "number") return "number";
  if (field?.type === "date") return "date";
  return "text";
}

function hasActiveFilter(filter) {
  if (!filter) return false;
  if (filter.operator === "is_empty" || filter.operator === "is_not_empty") return true;
  if (filter.operator === "between") return Boolean(String(filter.value || "").trim() || String(filter.valueTo || "").trim());
  return Boolean(String(filter.value || "").trim());
}

function filterTagLabel(filter, fields) {
  const field = fieldByName(fields, filter.field);
  const operator = operatorsForField(field).find((item) => item.value === filter.operator);
  if (filter.operator === "is_empty" || filter.operator === "is_not_empty") return `${field.label} ${operator?.label}`;
  if (filter.operator === "between") return `${field.label} entre ${filter.value || "-"} e ${filter.valueTo || "-"}`;
  const value = field.type === "boolean" ? (String(filter.value) === "true" ? "Sim" : "Nao") : filter.value;
  return `${field.label} ${operator?.label || filter.operator} ${value}`;
}

function filterRows(items, query, fields) {
  if (!Array.isArray(query)) {
    const term = String(query || "").trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => fields.some((field) => String(item[field] || "").toLowerCase().includes(term)));
  }
  const activeFilters = query.filter(hasActiveFilter);
  if (!activeFilters.length) return items;
  return items.filter((item) => activeFilters.every((filter) => {
    if (filter.field === "__all__") return fields.some((field) => compareBrowserValue(item[field.name], filter, { ...field, type: "text" }));
    const field = fieldByName(fields, filter.field);
    return compareBrowserValue(item[field.name], filter, field);
  }));
}

function compareBrowserValue(rawValue, filter, field) {
  const empty = rawValue === null || rawValue === undefined || rawValue === "";
  if (filter.operator === "is_empty") return empty;
  if (filter.operator === "is_not_empty") return !empty;
  if (field.type === "boolean") return String(Boolean(rawValue)) === String(filter.value || "true");
  if (field.type === "number" || field.type === "date") {
    const value = field.type === "number" ? Number(rawValue) : String(rawValue || "").slice(0, 10);
    const start = field.type === "number" ? Number(filter.value) : filter.value;
    const end = field.type === "number" ? Number(filter.valueTo) : filter.valueTo;
    if (filter.operator === "between") return (!filter.value || value >= start) && (!filter.valueTo || value <= end);
    if (filter.operator === "greater_than") return value > start;
    if (filter.operator === "greater_or_equal") return value >= start;
    if (filter.operator === "less_than") return value < start;
    if (filter.operator === "less_or_equal") return value <= start;
    return value === start;
  }
  const value = String(rawValue || "").toUpperCase();
  const term = String(filter.value || "").toUpperCase();
  if (filter.operator === "equals") return value === term;
  if (filter.operator === "starts_with") return value.startsWith(term);
  if (filter.operator === "ends_with") return value.endsWith(term);
  if (filter.operator === "not_contains") return !value.includes(term);
  return value.includes(term);
}

function suggestedProductPrice(costPrice, marginPercent) {
  const cost = Number(costPrice || 0);
  const margin = Number(marginPercent || 0);
  if (!Number.isFinite(cost) || !Number.isFinite(margin)) return "0.00";
  return (cost * (1 + margin / 100)).toFixed(2);
}

createRoot(document.getElementById("root")).render(<App />);
