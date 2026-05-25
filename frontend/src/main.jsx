import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Box, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, Edit3, HelpCircle, Home, Layers3, Menu, Moon, Package, Plus, RefreshCcw, Send, Sun, Tags, Trash2, Users, X, XCircle } from "lucide-react";
import api from "./services/api";
import "./styles.css";

const today = new Date().toISOString().slice(0, 10);
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const percent = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const emptyCustomer = { customer_profile_id: "", name: "", document_number: "", email: "", phone: "", city: "", state_code: "", active: true };
const emptyCustomerProfile = { code: "", name: "", description: "", max_inactive_days: "180", max_overdue_days: "0", block_without_movement: false, block_overdue_titles: true, active: true };
const emptyGroup = { code: "", name: "", description: "", active: true };
const emptyClass = { product_group_id: "", code: "", name: "", description: "", active: true };
const emptyProduct = { product_group_id: "", product_class_id: "", sku: "", name: "", unit: "UN", purchase_price: "0.00", cost_price: "0.00", sale_price: "0.00", description: "", active: true };
const emptyPriceTable = { code: "", name: "", correction_mode: "outside", monthly_rate: "0.00", base_date: today, active: true };
const emptyPriceItem = { product_id: "", base_price: "0.00", margin_percent: "5.00", active: true };
const emptyPriceTier = { min_quantity: "1.00", discount_percent: "0.00", active: true };
const emptyOrder = { customer_id: "", price_table_id: "", warehouse_id: "", order_type: "sale", order_date: today, payment_due_date: today, delivery_date: "", notes: "" };
const emptyOrderItem = { product_id: "", warehouse_id: "", quantity: "1", negotiated_unit_price: "" };

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

function App() {
  const [activeTab, setActiveTab] = useState("home");
  const [theme, setTheme] = useState(() => localStorage.getItem("easysales-theme") || "light");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState({ cadastros: true, operacoes: true });
  const [health, setHealth] = useState(null);
  const [message, setMessage] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [customerProfiles, setCustomerProfiles] = useState([]);
  const [groups, setGroups] = useState([]);
  const [classes, setClasses] = useState([]);
  const [products, setProducts] = useState([]);
  const [priceTables, setPriceTables] = useState([]);
  const [orders, setOrders] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [customerMonitoring, setCustomerMonitoring] = useState([]);

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("easysales-theme", theme);
  }, [theme]);

  async function loadAll() {
    try {
      const [healthRes, customersRes, monitoringRes, profilesRes, groupsRes, classesRes, productsRes, priceTablesRes, ordersRes, warehousesRes] = await Promise.all([
        api.get("/health"),
        api.get("/customers"),
        api.get("/customer-monitoring"),
        api.get("/customer-profiles"),
        api.get("/product-groups"),
        api.get("/product-classes"),
        api.get("/products"),
        api.get("/price-tables"),
        api.get("/orders"),
        api.get("/warehouses"),
      ]);
      setHealth(healthRes.data);
      setCustomers(customersRes.data);
      setCustomerMonitoring(monitoringRes.data);
      setCustomerProfiles(profilesRes.data);
      setGroups(groupsRes.data);
      setClasses(classesRes.data);
      setProducts(productsRes.data);
      setPriceTables(priceTablesRes.data);
      setOrders(ordersRes.data);
      setWarehouses(warehousesRes.data);
      setMessage(null);
    } catch (error) {
      setMessage(errorMessage(error, MESSAGES.apiUnavailable));
    }
  }

  function openTab(tab) {
    setActiveTab(tab);
    setMessage(null);
  }

  const pageMeta = {
    home: ["Visao geral", "Home"],
    products: ["Cadastros", "Produtos"],
    priceTables: ["Cadastros", "Tabelas de preco"],
    groups: ["Cadastros", "Grupos de produtos"],
    classes: ["Cadastros", "Classes de produtos"],
    customers: ["Cadastros", "Clientes"],
    customerProfiles: ["Cadastros", "Perfis comerciais"],
    orders: ["Operacoes", "Pedidos"],
    customerManagement: ["Operacoes", "Gestao de clientes"],
    approvals: ["Operacoes", "Autorizacoes"],
  }[activeTab] || ["EasySales", "EasySales"];

  async function run(action) {
    try {
      await action();
      await loadAll();
      setMessage(createMessage(MESSAGE_TYPES.success, MESSAGES.operationSuccess));
      return true;
    } catch (error) {
      setMessage(errorMessage(error));
      return false;
    }
  }

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

        <MenuGroup title="Cadastros" open={menuOpen.cadastros} collapsed={sidebarCollapsed} onToggle={() => setMenuOpen((current) => ({ ...current, cadastros: !current.cadastros }))}>
          <NavButton active={activeTab === "products"} onClick={() => openTab("products")} icon={Box} label="Produtos" />
          <NavButton active={activeTab === "priceTables"} onClick={() => openTab("priceTables")} icon={Tags} label="Tabelas de preco" />
          <NavButton active={activeTab === "groups"} onClick={() => openTab("groups")} icon={Layers3} label="Grupos" />
          <NavButton active={activeTab === "classes"} onClick={() => openTab("classes")} icon={Layers3} label="Classes" />
          <NavButton active={activeTab === "customers"} onClick={() => openTab("customers")} icon={Users} label="Clientes" />
          <NavButton active={activeTab === "customerProfiles"} onClick={() => openTab("customerProfiles")} icon={Users} label="Perfis comerciais" />
        </MenuGroup>

        <MenuGroup title="Operacoes" open={menuOpen.operacoes} collapsed={sidebarCollapsed} onToggle={() => setMenuOpen((current) => ({ ...current, operacoes: !current.operacoes }))}>
          <NavButton active={activeTab === "orders"} onClick={() => openTab("orders")} icon={ClipboardList} label="Pedidos" />
          <NavButton active={activeTab === "customerManagement"} onClick={() => openTab("customerManagement")} icon={Users} label="Gestao clientes" />
          <NavButton active={activeTab === "approvals"} onClick={() => openTab("approvals")} icon={CheckCircle2} label="Autorizacoes" />
        </MenuGroup>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p>{pageMeta[0]}</p>
            <h1>{pageMeta[1]}</h1>
          </div>
          <div className="topbar-actions">
            <button className="secondary-button" onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />} {theme === "dark" ? "Claro" : "Escuro"}
            </button>
            <button className="secondary-button" onClick={loadAll}><RefreshCcw size={17} /> Atualizar</button>
          </div>
        </header>

        {message && <div className={`message ${message.type}`}>{message.text}</div>}

        {activeTab === "home" && <HomePage orders={orders} customers={customers} products={products} priceTables={priceTables} customerMonitoring={customerMonitoring} openTab={openTab} />}
        {activeTab === "products" && <ProductsBrowser products={products} groups={groups} classes={classes} run={run} />}
        {activeTab === "priceTables" && <PriceTablesBrowser priceTables={priceTables} products={products} run={run} />}
        {activeTab === "groups" && <SimpleCatalogBrowser title="Grupos de produtos" eyebrow="Cadastros" endpoint="/product-groups" items={groups} template={emptyGroup} run={run} />}
        {activeTab === "classes" && <ClassesBrowser classes={classes} groups={groups} run={run} />}
        {activeTab === "customers" && <CustomersBrowser customers={customers} customerProfiles={customerProfiles} run={run} />}
        {activeTab === "customerProfiles" && <CustomerProfilesBrowser profiles={customerProfiles} run={run} />}
        {activeTab === "orders" && <OrdersBrowser orders={orders} customers={customers} products={products} priceTables={priceTables} warehouses={warehouses} run={run} />}
        {activeTab === "customerManagement" && <CustomerManagementPage rows={customerMonitoring} run={run} />}
        {activeTab === "approvals" && <OrderApprovalsPage orders={orders} run={run} />}
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

function ProductsBrowser({ products, groups, classes, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(products, query, ["sku", "name", "product_group_name", "product_class_name"]), [products, query]);

  function toForm(item) {
    return item ? { product_group_id: item.product_group_id || "", product_class_id: item.product_class_id || "", sku: item.sku, name: item.name, unit: item.unit, purchase_price: String(item.purchase_price || "0.00"), cost_price: String(item.cost_price || "0.00"), sale_price: String(item.sale_price || "0.00"), description: item.description || "", active: item.active } : emptyProduct;
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
      sale_price: Number(form.sale_price || 0),
      description: form.description.trim() || null,
      active: form.active,
    };
    await run(() => item ? api.put(`/products/${item.id}`, payload) : api.post("/products", payload));
    setModal(null);
  }

  return (
    <Browser title="Produtos" eyebrow="Cadastros" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <DataTable columns={["SKU", "Produto", "Grupo", "Compra", "Custo", "Venda ref.", "Status", "Acoes"]} rows={rows.map((item) => [
        item.sku,
        item.name,
        item.product_group_name || "-",
        money.format(Number(item.purchase_price || 0)),
        money.format(Number(item.cost_price || 0)),
        money.format(Number(item.sale_price || 0)),
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/products/${item.id}`))} />,
      ])} />
      {modal && <ProductModal state={modal} setState={setModal} groups={groups} classes={classes} onSave={save} />}
    </Browser>
  );
}

function ProductModal({ state, setState, groups, classes, onSave }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  return (
    <Modal title={item ? "Editar produto" : "Novo produto"} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="modal-grid">
        <Field label="SKU"><input required value={form.sku} onChange={(e) => update("sku", e.target.value.toUpperCase())} /></Field>
        <Field label="Produto"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="Grupo"><Select value={form.product_group_id} onChange={(v) => update("product_group_id", v)} options={groups} empty="Sem grupo" /></Field>
        <Field label="Classe"><Select value={form.product_class_id} onChange={(v) => update("product_class_id", v)} options={classes} empty="Sem classe" /></Field>
        <Field label="Unidade"><input value={form.unit} onChange={(e) => update("unit", e.target.value.toUpperCase())} /></Field>
        <Field label="Preco compra"><input type="number" min="0" step="0.01" value={form.purchase_price} onChange={(e) => update("purchase_price", e.target.value)} /></Field>
        <Field label="Custo"><input type="number" min="0" step="0.01" value={form.cost_price} onChange={(e) => update("cost_price", e.target.value)} /></Field>
        <Field label="Preco referencia"><input type="number" min="0" step="0.01" value={form.sale_price} onChange={(e) => update("sale_price", e.target.value)} /></Field>
        <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
        <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
      </div>
    </Modal>
  );
}

function PriceTablesBrowser({ priceTables, products, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(priceTables, query, ["code", "name", "correction_mode"]), [priceTables, query]);

  function toForm(item) {
    return item ? { code: item.code, name: item.name, correction_mode: item.correction_mode, monthly_rate: String(item.monthly_rate || "0.00"), base_date: item.base_date, active: item.active } : emptyPriceTable;
  }

  async function save(form, item) {
    const payload = { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(), monthly_rate: Number(form.monthly_rate || 0) };
    await run(() => item ? api.put(`/price-tables/${item.id}`, payload) : api.post("/price-tables", payload));
    setModal(null);
  }

  return (
    <Browser title="Tabelas de preco" eyebrow="Cadastros" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <DataTable columns={["Codigo", "Nome", "Correcao", "Taxa mensal", "Data base", "Status", "Acoes"]} rows={rows.map((item) => [
        item.code,
        item.name,
        item.correction_mode === "inside" ? "Por dentro" : "Por fora",
        `${Number(item.monthly_rate || 0).toLocaleString("pt-BR")}%`,
        item.base_date,
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/price-tables/${item.id}`))} />,
      ])} />

      {modal && <PriceTableModal state={modal} setState={setModal} products={products} run={run} onSave={save} />}
    </Browser>
  );
}

function PriceTableModal({ state, setState, products, run, onSave }) {
  const { item, form } = state;
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

  return (
    <Modal title={item ? "Editar tabela de preco" : "Nova tabela de preco"} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="modal-grid">
        <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
        <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="Correcao"><select value={form.correction_mode} onChange={(e) => update("correction_mode", e.target.value)}><option value="outside">Por fora</option><option value="inside">Por dentro</option></select></Field>
        <Field label="Taxa mensal %"><input type="number" step="0.0001" value={form.monthly_rate} onChange={(e) => update("monthly_rate", e.target.value)} /></Field>
        <Field label="Data base"><input type="date" value={form.base_date} onChange={(e) => update("base_date", e.target.value)} /></Field>
        <Check label="Ativa" checked={form.active} onChange={(v) => update("active", v)} />
      </div>

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
    </Modal>
  );
}

function SimpleCatalogBrowser({ title, eyebrow, endpoint, items, template, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(items, query, ["code", "name", "description"]), [items, query]);

  async function save(form, item) {
    const payload = { ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description.trim() || null };
    await run(() => item ? api.put(`${endpoint}/${item.id}`, payload) : api.post(endpoint, payload));
    setModal(null);
  }

  return (
    <Browser title={title} eyebrow={eyebrow} query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: template })}>
      <DataTable columns={["Codigo", "Nome", "Descricao", "Status", "Acoes"]} rows={rows.map((item) => [
        item.code,
        item.name,
        item.description || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: { code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`${endpoint}/${item.id}`))} />,
      ])} />
      {modal && <SimpleCatalogModal title={title} state={modal} setState={setModal} onSave={save} />}
    </Browser>
  );
}

function SimpleCatalogModal({ title, state, setState, onSave }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  return (
    <Modal title={item ? `Editar ${title.toLowerCase()}` : title} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="modal-grid">
        <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
        <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
        <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
      </div>
    </Modal>
  );
}

function ClassesBrowser({ classes, groups, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(classes, query, ["code", "name", "product_group_name", "description"]), [classes, query]);

  async function save(form, item) {
    const payload = { ...form, product_group_id: form.product_group_id ? Number(form.product_group_id) : null, code: form.code.trim().toUpperCase(), name: form.name.trim(), description: form.description.trim() || null };
    await run(() => item ? api.put(`/product-classes/${item.id}`, payload) : api.post("/product-classes", payload));
    setModal(null);
  }

  return (
    <Browser title="Classes de produtos" eyebrow="Cadastros" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: emptyClass })}>
      <DataTable columns={["Codigo", "Nome", "Grupo", "Descricao", "Status", "Acoes"]} rows={rows.map((item) => [
        item.code,
        item.name,
        item.product_group_name || "-",
        item.description || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: { product_group_id: item.product_group_id || "", code: item.code, name: item.name, description: item.description || "", active: item.active } })} onRemove={() => run(() => api.delete(`/product-classes/${item.id}`))} />,
      ])} />
      {modal && <ClassModal state={modal} setState={setModal} groups={groups} onSave={save} />}
    </Browser>
  );
}

function ClassModal({ state, setState, groups, onSave }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  return (
    <Modal title={item ? "Editar classe" : "Nova classe"} onClose={() => setState(null)} onSubmit={() => onSave(form, item)}>
      <div className="modal-grid">
        <Field label="Codigo"><input required value={form.code} onChange={(e) => update("code", e.target.value.toUpperCase())} /></Field>
        <Field label="Nome"><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="Grupo" wide><Select value={form.product_group_id} onChange={(v) => update("product_group_id", v)} options={groups} empty="Sem grupo" /></Field>
        <Field label="Descricao" wide><input value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>
        <Check label="Ativa" checked={form.active} onChange={(v) => update("active", v)} />
      </div>
    </Modal>
  );
}

function CustomerProfilesBrowser({ profiles, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(profiles, query, ["code", "name", "description"]), [profiles, query]);

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
    };
    await run(() => item ? api.put(`/customer-profiles/${item.id}`, payload) : api.post("/customer-profiles", payload));
    setModal(null);
  }

  return (
    <Browser title="Perfis comerciais" eyebrow="Cadastros" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <DataTable columns={["Codigo", "Nome", "Dias sem mov.", "Titulos vencidos", "Bloqueios", "Status", "Acoes"]} rows={rows.map((item) => [
        item.code,
        item.name,
        item.max_inactive_days,
        item.max_overdue_days,
        [item.block_without_movement && "Sem mov.", item.block_overdue_titles && "Vencidos"].filter(Boolean).join(" / ") || "-",
        <Status active={item.active} />,
        <RowActions onEdit={() => setModal({ item, form: toForm(item) })} onRemove={() => run(() => api.delete(`/customer-profiles/${item.id}`))} />,
      ])} />
      {modal && <CustomerProfileModal state={modal} setState={setModal} onSave={save} />}
    </Browser>
  );
}

function CustomerProfileModal({ state, setState, onSave }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
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
    </Modal>
  );
}

function CustomersBrowser({ customers, customerProfiles, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(customers, query, ["name", "document_number", "email", "phone", "city", "customer_profile_name"]), [customers, query]);

  function localId(item) {
    return item.id?.startsWith("local:") ? item.id.replace("local:", "") : null;
  }

  async function save(form, item) {
    const payload = { ...form, customer_profile_id: form.customer_profile_id ? Number(form.customer_profile_id) : null, name: form.name.trim(), document_number: form.document_number || null, email: form.email || null, phone: form.phone || null, city: form.city || null, state_code: form.state_code || null };
    const id = item ? localId(item) : null;
    const saved = await run(() => {
      if (!payload.customer_profile_id) throw new Error(MESSAGES.customers.profileRequired);
      return id ? api.put(`/customers/${id}`, payload) : api.post("/customers", payload);
    });
    if (saved) setModal(null);
  }

  return (
    <Browser title="Clientes" eyebrow="Cadastros" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: emptyCustomer })}>
      <DataTable columns={["Cliente", "Documento", "Perfil", "Limite", "Contato", "Cidade/UF", "Origem", "Status", "Acoes"]} rows={rows.map((item) => {
        const id = localId(item);
        return [
          item.name,
          item.document_number || "-",
          item.customer_profile_name || "-",
          money.format(Number(item.credit_limit || 0)),
          item.email || item.phone || "-",
          [item.city, item.state_code].filter(Boolean).join(" / ") || "-",
          item.source,
          <Status active={item.active} />,
          id
            ? <RowActions onEdit={() => setModal({ item, form: { customer_profile_id: item.customer_profile_id || "", name: item.name, document_number: item.document_number || "", email: item.email || "", phone: item.phone || "", city: item.city || "", state_code: item.state_code || "", active: item.active } })} onRemove={() => run(() => api.delete(`/customers/${id}`))} />
            : <button type="button" className="link-button" onClick={() => setModal({ item, form: { customer_profile_id: item.customer_profile_id || "", name: item.name, document_number: item.document_number || "", email: item.email || "", phone: item.phone || "", city: item.city || "", state_code: item.state_code || "", active: item.active } })}>Perfil</button>,
        ];
      })} />
      {modal && <CustomerModal state={modal} setState={setModal} customerProfiles={customerProfiles} onSave={save} run={run} />}
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

function CustomerModal({ state, setState, customerProfiles, onSave, run }) {
  const { item, form } = state;
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });
  const isShared = item?.id?.startsWith("easyfinance:");
  async function saveSharedProfile() {
    const [source, externalId] = item.id.split(":");
    const saved = await run(() => {
      if (!form.customer_profile_id) throw new Error(MESSAGES.customers.profileRequired);
      return api.put(`/customers/${source}/${externalId}/profile`, { customer_profile_id: Number(form.customer_profile_id) });
    });
    if (saved) setState(null);
  }
  return (
    <Modal title={item ? "Editar cliente" : "Novo cliente"} onClose={() => setState(null)} onSubmit={() => isShared ? saveSharedProfile() : onSave(form, item)}>
      <div className="modal-grid">
        <Field label="Perfil comercial" wide><Select required value={form.customer_profile_id} onChange={(v) => update("customer_profile_id", v)} options={customerProfiles} empty="Selecione" /></Field>
        {isShared && <Field label="Limite de credito"><input disabled value={money.format(Number(item.credit_limit || 0))} /></Field>}
        <Field label="Nome" wide><input required value={form.name} onChange={(e) => update("name", e.target.value)} /></Field>
        <Field label="CPF/CNPJ"><input value={form.document_number} onChange={(e) => update("document_number", e.target.value)} /></Field>
        <Field label="E-mail"><input value={form.email} onChange={(e) => update("email", e.target.value)} /></Field>
        <Field label="Telefone"><input value={form.phone} onChange={(e) => update("phone", e.target.value)} /></Field>
        <Field label="Cidade"><input value={form.city} onChange={(e) => update("city", e.target.value)} /></Field>
        <Field label="UF"><input maxLength="2" value={form.state_code} onChange={(e) => update("state_code", e.target.value.toUpperCase())} /></Field>
        <Check label="Ativo" checked={form.active} onChange={(v) => update("active", v)} />
      </div>
    </Modal>
  );
}

function OrdersBrowser({ orders, customers, products, priceTables, warehouses, run }) {
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const rows = useMemo(() => filterRows(orders, query, ["order_number", "order_type", "customer_name", "price_table_name", "status"]), [orders, query]);

  function toForm(item) {
    if (!item) return emptyOrder;
    return { customer_id: `${item.customer_source}:${item.customer_external_id}`, price_table_id: item.price_table_id || "", warehouse_id: item.warehouse_id || "", order_type: item.order_type || "sale", order_date: item.order_date, payment_due_date: item.payment_due_date, delivery_date: item.delivery_date || "", notes: item.notes || "" };
  }

  async function save(form, item) {
    const payload = { customer_id: form.customer_id, price_table_id: Number(form.price_table_id), warehouse_id: form.warehouse_id ? Number(form.warehouse_id) : null, order_type: form.order_type || "sale", order_date: form.order_date, payment_due_date: form.payment_due_date, delivery_date: form.delivery_date || null, notes: form.notes.trim() || null, items: item ? item.items.map((row) => ({ product_id: row.product_id, warehouse_id: row.warehouse_id || null, quantity: row.quantity, negotiated_unit_price: row.negotiated_unit_price })) : [] };
    await run(() => item ? api.put(`/orders/${item.id}`, payload) : api.post("/orders", payload));
    setModal(null);
  }

  return (
    <Browser title="Pedidos" eyebrow="Operacoes" query={query} setQuery={setQuery} onNew={() => setModal({ item: null, form: toForm(null) })}>
      <OrderLegend />
      <DataTable className="orders-table" columns={["Pedido", "Tipo", "Cliente", "Tabela", "Pedido em", "Pagamento", "Entrega", "Total", "Lucro", "Rentab.", "Status", "Acoes"]} rows={rows.map((item) => ({
        className: orderRowClassName(item),
        cells: [
          item.order_number,
          orderTypeLabel(item.order_type),
          item.customer_name,
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
      }))} />
      {modal && <OrderModal state={modal} setState={setModal} customers={customers} products={products} priceTables={priceTables} warehouses={warehouses} run={run} onSave={save} />}
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

function OrderModal({ state, setState, customers, products, priceTables, warehouses, run, onSave }) {
  const { item, form } = state;
  const [currentOrder, setCurrentOrder] = useState(item);
  const [itemForm, setItemForm] = useState(emptyOrderItem);
  const [editingItem, setEditingItem] = useState(null);
  const [preview, setPreview] = useState(null);
  const selectedPriceTable = priceTables.find((table) => Number(table.id) === Number(form.price_table_id));
  const correctionHelp = priceCorrectionHelp(preview, selectedPriceTable);
  const update = (field, value) => setState({ ...state, form: { ...form, [field]: value } });

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
    const payload = { customer_id: form.customer_id, price_table_id: Number(form.price_table_id), warehouse_id: form.warehouse_id ? Number(form.warehouse_id) : null, order_type: form.order_type || "sale", order_date: form.order_date, payment_due_date: form.payment_due_date, delivery_date: form.delivery_date || null, notes: form.notes.trim() || null, items: currentOrder?.items?.map((row) => ({ product_id: row.product_id, warehouse_id: row.warehouse_id || null, quantity: Number(row.quantity || 0), negotiated_unit_price: Number(row.negotiated_unit_price || row.corrected_unit_price || 0) })) || [] };
    const response = currentOrder
      ? await api.put(`/orders/${currentOrder.id}`, payload)
      : await api.post("/orders", { ...payload, items: [] });
    setCurrentOrder(response.data);
    await run(async () => response);
  }

  async function reloadOrder(orderId) {
    const response = await api.get(`/orders/${orderId}`);
    setCurrentOrder(response.data);
  }

  async function submitOrder() {
    if (!currentOrder?.id) return;
    const response = await api.post(`/orders/${currentOrder.id}/submit`);
    setCurrentOrder(response.data);
    await run(async () => response);
  }

  async function saveOrderItem() {
    if (!currentOrder?.id || !itemForm.product_id) return;
    const payload = { product_id: Number(itemForm.product_id), warehouse_id: itemForm.warehouse_id ? Number(itemForm.warehouse_id) : (form.warehouse_id ? Number(form.warehouse_id) : null), quantity: Number(itemForm.quantity || 0), negotiated_unit_price: itemForm.negotiated_unit_price ? Number(itemForm.negotiated_unit_price) : null };
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

  function editOrderItem(row) {
    setEditingItem(row);
    setItemForm({ product_id: row.product_id || "", warehouse_id: row.warehouse_id || form.warehouse_id || "", quantity: String(row.quantity || "1"), negotiated_unit_price: String(row.negotiated_unit_price || row.corrected_unit_price || "") });
  }

  return (
    <Modal title={currentOrder ? `Editar pedido ${currentOrder.order_number}` : "Novo pedido"} onClose={() => setState(null)} onSubmit={() => onSave(form, currentOrder)}>
      <div className="modal-grid">
        <Field label="Cliente" wide><Select value={form.customer_id} onChange={(v) => update("customer_id", v)} options={customers} empty="Selecione" required labelKey="name" valueKey="id" /></Field>
        <Field label="Local padrao"><Select value={form.warehouse_id} onChange={(v) => update("warehouse_id", v)} options={warehouses} empty="Selecione" /></Field>
        <Field label="Tipo"><select value={form.order_type || "sale"} onChange={(event) => update("order_type", event.target.value)}><option value="sale">Pedido de venda</option><option value="purchase">Pedido de compra</option></select></Field>
        <Field label="Tabela"><Select value={form.price_table_id} onChange={(v) => update("price_table_id", v)} options={priceTables} empty="Selecione" required /></Field>
        <Field label="Prazo pagamento"><input type="date" value={form.payment_due_date} onChange={(e) => update("payment_due_date", e.target.value)} /></Field>
        <Field label="Previsao entrega"><input type="date" value={form.delivery_date} onChange={(e) => update("delivery_date", e.target.value)} /></Field>
        <Field label="Data pedido"><input type="date" value={form.order_date} onChange={(e) => update("order_date", e.target.value)} /></Field>
        <Field label="Observacao" wide><input value={form.notes} onChange={(e) => update("notes", e.target.value)} /></Field>
        {currentOrder?.approval_notes && <Field label="Autorizacao" wide><input disabled value={currentOrder.approval_notes} /></Field>}
        <div className="form-actions"><button type="button" className="secondary-button" onClick={saveHeader}>{currentOrder ? "Salvar cabecalho" : "Salvar cabecalho para itens"}</button></div>
        {currentOrder?.status === "draft" && <div className="form-actions"><button type="button" className="primary-button" onClick={submitOrder}><Send size={16} /> Enviar para aprovacao</button></div>}
        {currentOrder?.id && !["cancelled", "rejected"].includes(currentOrder.status) && <div className="form-actions"><button type="button" className="secondary-button" onClick={cancelOrder}>Cancelar pedido</button></div>}
      </div>

      <section className="modal-detail">
        {currentOrder?.id && (
          <div className="order-context">
            <span>Tipo <strong>{orderTypeLabel(currentOrder.order_type)}</strong></span>
            <span>Status <OrderStatus status={currentOrder.status} overdue={isOrderDeliveryOverdue(currentOrder)} /></span>
            <span>Pagamento <strong>{currentOrder.payment_due_date}</strong></span>
            <span>Entrega <strong>{currentOrder.delivery_date || "Nao informada"}</strong></span>
            <span>Local padrao <strong>{currentOrder.warehouse_name || "-"}</strong></span>
            <span>Cliente <strong>{currentOrder.customer_name}</strong></span>
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
              <Field label="Produto" wide><Select value={itemForm.product_id} onChange={(v) => setItemForm({ ...itemForm, product_id: v, negotiated_unit_price: "" })} options={products} empty="Selecione" /></Field>
              <Field label="Local"><Select value={itemForm.warehouse_id || form.warehouse_id} onChange={(v) => setItemForm({ ...itemForm, warehouse_id: v })} options={warehouses} empty="Padrao do pedido" /></Field>
              <Field label="Quantidade"><input type="number" min="0.0001" step="0.0001" value={itemForm.quantity} onChange={(e) => setItemForm({ ...itemForm, quantity: e.target.value, negotiated_unit_price: "" })} /></Field>
              <Field label="Valor negociado"><input type="number" min="0" step="0.01" value={itemForm.negotiated_unit_price} onChange={(e) => setItemForm({ ...itemForm, negotiated_unit_price: e.target.value })} /></Field>
              <div className="form-actions">
                {editingItem && <button type="button" className="secondary-button" onClick={() => { setEditingItem(null); setItemForm(emptyOrderItem); }}>Cancelar item</button>}
                <button type="button" className="primary-button" onClick={saveOrderItem}>{editingItem ? "Salvar item" : "Incluir item"}</button>
              </div>
            </div>
            <DataTable columns={["Produto", "Local", "Qtd.", "Cancel.", "Preco tabela", "Negociado", "Comercial", "Total", "Lucro", "Acoes"]} rows={(currentOrder.items || []).map((row) => [
              `${row.product_sku} - ${row.product_name}`,
              row.warehouse_name || currentOrder.warehouse_name || "-",
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
    </Modal>
  );
}

function Browser({ title, eyebrow, query, setQuery, onNew, children }) {
  return (
    <section className="panel">
      <div className="browser-header">
        <div>
          <p>{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        <div className="browser-actions">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar..." />
          <button className="primary-button" onClick={onNew}><Plus size={17} /> Novo</button>
        </div>
      </div>
      {children}
    </section>
  );
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
  return (
    <div className="table-wrap">
      <table className={className}>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => {
            const cells = Array.isArray(row) ? row : row.cells;
            return <tr key={index} className={Array.isArray(row) ? "" : row.className}>{cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>;
          })}
          {rows.length === 0 && <tr><td colSpan={columns.length} className="empty">Nenhum registro encontrado.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function filterRows(items, query, fields) {
  const term = query.trim().toLowerCase();
  if (!term) return items;
  return items.filter((item) => fields.some((field) => String(item[field] || "").toLowerCase().includes(term)));
}

createRoot(document.getElementById("root")).render(<App />);
