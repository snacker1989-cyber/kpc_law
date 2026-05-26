document.querySelectorAll(".tree-toggle").forEach((button) => {
    button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.target);
        const symbol = button.querySelector(".toggle-symbol");
        if (!target || !symbol) return;
        const collapsed = target.hidden;
        target.hidden = !collapsed;
        button.setAttribute("aria-expanded", String(collapsed));
        symbol.textContent = collapsed ? "-" : "+";
    });
});

const modal = document.getElementById("section-modal");
const modalContent = document.getElementById("section-modal-content");
const closeButton = document.querySelector(".modal-close");

function closeModal() {
    if (!modal || !modalContent) return;
    modal.hidden = true;
    modalContent.innerHTML = "";
}

document.querySelectorAll(".internal-ref").forEach((button) => {
    button.addEventListener("click", async () => {
        if (!modal || !modalContent) return;
        const response = await fetch(`/section-links/${button.dataset.linkId}/preview`);
        modalContent.innerHTML = response.ok ? await response.text() : "<p>연결된 조문을 찾을 수 없습니다.</p>";
        modal.hidden = false;
    });
});

if (closeButton) {
    closeButton.addEventListener("click", closeModal);
}

if (modal) {
    modal.addEventListener("click", (event) => {
        if (event.target === modal) closeModal();
    });
}
