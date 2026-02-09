import { Controller } from "@hotwired/stimulus";
import { showMessage } from "../utils/messages";

export default class extends Controller {
    static targets = [
        "item",
        "formContainer",
        "toggleButton",
        "onboardingModal",
        "onboardingOverlay"
    ];

    connect() {
        if (this.shouldSkipOnboarding()) {
            this.hideOnboarding();
        }
    }

    toggleForm(event) {
        event.preventDefault();
        this.formContainerTarget.classList.toggle("hidden");

        if (this.formContainerTarget.classList.contains("hidden")) {
            this.toggleButtonTarget.textContent = "Add Sitemap";
        } else {
            this.toggleButtonTarget.textContent = "Cancel";
        }
    }

    skipOnboarding(event) {
        event.preventDefault();

        this.setSkipOnboarding();
        this.hideOnboarding();
    }

    showOnboarding(event) {
        event.preventDefault();

        if (this.hasOnboardingModalTarget) {
            this.onboardingModalTarget.classList.remove("hidden");
        }

        if (this.hasOnboardingOverlayTarget) {
            this.onboardingOverlayTarget.classList.remove("hidden");
        }
    }

    async delete(event) {
        event.preventDefault();

        const button = event.currentTarget;
        const sitemapId = button.dataset.sitemapId;
        const sitemapUrl = button.dataset.sitemapUrl;

        if (!confirm(`Are you sure you want to delete this sitemap?\n\n${sitemapUrl}`)) {
            return;
        }

        try {
            const response = await fetch(`/api/sitemaps/${sitemapId}`, {
                method: "DELETE",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.getCsrfToken()
                }
            });

            const data = await response.json();

            if (response.ok && data.success) {
                const itemElement = button.closest('[data-sitemap-target="item"]');
                if (itemElement) {
                    itemElement.remove();
                }

                const remainingItems = this.itemTargets.length;
                if (remainingItems === 0) {
                    location.reload();
                }

                showMessage(data.message, "success");
            } else {
                showMessage(data.message || "Failed to delete sitemap", "error");
            }
        } catch (error) {
            console.error("Error deleting sitemap:", error);
            showMessage("An error occurred while deleting the sitemap", "error");
        }
    }

    getCsrfToken() {
        return document.querySelector("[name=csrfmiddlewaretoken]").value;
    }

    hideOnboarding() {
        if (this.hasOnboardingModalTarget) {
            this.onboardingModalTarget.classList.add("hidden");
        }

        if (this.hasOnboardingOverlayTarget) {
            this.onboardingOverlayTarget.classList.add("hidden");
        }
    }

    shouldSkipOnboarding() {
        try {
            return localStorage.getItem("skipOnboarding") === "true";
        } catch (error) {
            return false;
        }
    }

    setSkipOnboarding() {
        try {
            localStorage.setItem("skipOnboarding", "true");
        } catch (error) {
            // Ignore localStorage errors (e.g., private browsing).
        }
    }
}
